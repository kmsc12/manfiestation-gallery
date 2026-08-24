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
    """Make a request to the Notion API."""

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
    """Retrieve every page from the Notion data source."""

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
    """Extract the database title."""

    for property_data in properties.values():

        if property_data.get("type") == "title":

            title_parts = property_data.get("title", [])

            return "".join(
                part.get("plain_text", "")
                for part in title_parts
            ).strip()

    return "Untitled"


def get_checkbox(properties, name):
    """Read a checkbox property."""

    property_data = properties.get(name)

    if not property_data:
        return False

    if property_data.get("type") != "checkbox":
        return False

    return property_data.get("checkbox", False)


def get_tag(properties):
    """Read the Tag select property."""

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
    """Read the Notes property."""

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


def get_page_images(page_id):
    """
    Find images inside a Notion page.

    Notion-hosted image URLs expire, so we download them
    during the GitHub Action and serve local copies.
    """

    images = []

    cursor = None

    while True:

        endpoint = f"/blocks/{page_id}/children?page_size=100"

        if cursor:
            endpoint += f"&start_cursor={cursor}"

        response = notion_request(
            "GET",
            endpoint
        )

        for block in response.get("results", []):

            block_type = block.get("type")

            if block_type != "image":
                continue

            image_data = block.get("image", {})

            image_type = image_data.get("type")

            if image_type == "file":
                url = image_data.get("file", {}).get("url")

            elif image_type == "external":
                url = image_data.get("external", {}).get("url")

            else:
                url = None

            if url:
                images.append(url)

        if not response.get("has_more"):
            break

        cursor = response.get("next_cursor")

        if not cursor:
            break

    return images


def download_image(url, filename):
    """Download a Notion image into the repository."""

    destination = IMAGE_DIR / filename

    try:

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ManifestationGallery/1.0"
            }
        )

        with urllib.request.urlopen(request) as response:

            with open(destination, "wb") as file:
                file.write(response.read())

        return str(destination)

    except Exception as error:

        print(f"Could not download image: {error}")

        return None


def main():

    print("Connecting to Notion...")

    pages = get_all_pages()

    print(f"Found {len(pages)} Notion pages.")

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    manifestations = []

    for index, page in enumerate(pages):

        properties = page.get("properties", {})

        title = get_title(properties)

        done = get_checkbox(properties, "Done")

        tag = get_tag(properties)

        notes = get_notes(properties)

        print(f"[{index + 1}/{len(pages)}] {title}")

        # Do not include completed manifestations.
        if done:
            continue

        page_id = page.get("id")

        image_urls = get_page_images(page_id)

        local_images = []

        for image_index, image_url in enumerate(image_urls):

            filename = (
                f"{page_id.replace('-', '')}"
                f"-{image_index}.jpg"
            )

            local_path = download_image(
                image_url,
                filename
            )

            if local_path:

                local_images.append(
                    local_path.replace("\\", "/")
                )

        manifestations.append({
            "id": page_id,
            "title": title,
            "tag": tag,
            "notes": notes,
            "images": local_images,
        })

        # Be polite to the Notion API.
        time.sleep(0.35)

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            manifestations,
            file,
            ensure_ascii=False,
            indent=2
        )

    print()
    print(
        f"Saved {len(manifestations)} active manifestations."
    )


if __name__ == "__main__":
    main()
