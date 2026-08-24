import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path


NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATA_SOURCE_ID = "a30c375a-f25a-4204-89ee-b0708d8b7913"

NOTION_VERSION = "2026-03-11"
API_BASE = "https://api.notion.com/v1"

OUTPUT_FILE = Path("data/manifestations.json")
IMAGE_DIR = Path("images")


def notion_request(method, endpoint, body=None):
    url = API_BASE + endpoint

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    data = None

    if body is not None:
        data = json.dumps(body).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")

        print(f"Notion API error: HTTP {error.code}")
        print(error_body)

        raise


def get_all_pages():
    """Retrieve all pages from the Notion data source."""

    pages = []
    cursor = None

    while True:

        body = {
            "page_size": 100
        }

        if cursor:
            body["start_cursor"] = cursor

        response = notion_request(
            "POST",
            f"/data_sources/{DATA_SOURCE_ID}/query",
            body
        )

        pages.extend(response.get("results", []))

        if not response.get("has_more"):
            break

        cursor = response.get("next_cursor")

        if not cursor:
            break

    return pages


def get_title(properties):
    for property_data in properties.values():

        if property_data.get("type") == "title":

            title_parts = property_data.get("title", [])

            return "".join(
                part.get("plain_text", "")
                for part in title_parts
            ).strip()

    return "Untitled"


def get_checkbox(properties, name):
    property_data = properties.get(name)

    if not property_data:
        return False

    if property_data.get("type") != "checkbox":
        return False

    return property_data.get("checkbox", False)


def get_tag(properties):
    property_data = properties.get("Tag")

    if not property_data:
        return None

    if property_data.get("type") != "select":
        return None

    selected = property_data.get("select")

    if not selected:
        return None

    return selected.get("name")


def get_notes(properties):
    property_data = properties.get("Notes")

    if not property_data:
        return ""

    if property_data.get("type") != "rich_text":
        return ""

    parts = property_data.get("rich_text", [])

    return "".join(
        part.get("plain_text", "")
        for part in parts
    ).strip()


def get_cover_url(page):
    """
    Get the image URL from the Notion page cover.

    Supports both Notion-hosted covers and external covers.
    """

    cover = page.get("cover")

    if not cover:
        return None

    cover_type = cover.get("type")

    if cover_type == "file":
        return cover.get("file", {}).get("url")

    if cover_type == "external":
        return cover.get("external", {}).get("url")

    return None


def get_extension(content_type):
    """Choose a sensible image extension."""

    content_type = (content_type or "").lower()

    extensions = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }

    return extensions.get(content_type, ".jpg")


def download_image(url, filename):
    """Download a page cover and return its local path."""

    try:

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ManifestationGallery/1.0"
            }
        )

        with urllib.request.urlopen(request) as response:

            content_type = response.headers.get("Content-Type")
            extension = get_extension(content_type)

            destination = IMAGE_DIR / (
                Path(filename).stem + extension
            )

            with open(destination, "wb") as file:
                file.write(response.read())

        return str(destination).replace("\\", "/")

    except Exception as error:

        print(f"Could not download cover image: {error}")

        return None


def remove_page_images(page_id):
    """Remove cached cover images belonging to a page."""

    prefix = page_id.replace("-", "")

    for file in IMAGE_DIR.glob(f"{prefix}-*"):

        try:
            file.unlink()

            print(f"Removed old cover: {file}")

        except Exception as error:

            print(
                f"Could not remove {file}: {error}"
            )


def load_existing_data():
    """Load the previous gallery data."""

    if not OUTPUT_FILE.exists():
        return {}

    try:

        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        return {
            item["id"]: item
            for item in data.get(
                "manifestations",
                []
            )
        }

    except Exception:

        return {}


def main():

    print("Connecting to Notion...")

    IMAGE_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    existing = load_existing_data()

    pages = get_all_pages()

    print(
        f"Found {len(pages)} Notion pages."
    )

    manifestations = {}

    processed = 0
    skipped = 0

    for index, page in enumerate(pages):

        page_id = page.get("id")
        last_edited = page.get(
            "last_edited_time"
        )

        properties = page.get(
            "properties",
            {}
        )

        title = get_title(properties)

        done = get_checkbox(
            properties,
            "Done"
        )

        # Completed/materialised manifestations
        # are never displayed.
        if done:

            remove_page_images(page_id)

            continue

        previous = existing.get(page_id)

        # If nothing changed, reuse the existing
        # local data and image.
        if (
            previous
            and previous.get(
                "last_edited_time"
            ) == last_edited
        ):

            manifestations[page_id] = previous

            skipped += 1

            print(
                f"[{index + 1}/{len(pages)}] "
                f"Unchanged: {title}"
            )

            continue

        print(
            f"[{index + 1}/{len(pages)}] "
            f"Changed/new: {title}"
        )

        # Remove the previous cached cover.
        remove_page_images(page_id)

        tag = get_tag(properties)
        notes = get_notes(properties)

        cover_url = get_cover_url(page)

        local_images = []

        if cover_url:

            filename = (
                f"{page_id.replace('-', '')}-cover"
            )

            local_path = download_image(
                cover_url,
                filename
            )

            if local_path:
                local_images.append(local_path)

        manifestations[page_id] = {
            "id": page_id,
            "title": title,
            "tag": tag,
            "notes": notes,
            "images": local_images,
            "last_edited_time": last_edited,
        }

        processed += 1

        # Stay comfortably below Notion's API rate limit.
        time.sleep(0.35)

    output = {
        "manifestations": list(
            manifestations.values()
        )
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2
        )

    print()
    print(
        f"Changed/new pages processed: {processed}"
    )
    print(
        f"Unchanged pages reused: {skipped}"
    )
    print(
        f"Active manifestations: "
        f"{len(manifestations)}"
    )


if __name__ == "__main__":
    main()
