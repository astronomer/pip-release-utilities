import requests
import re
import subprocess
import argparse


def get_custom_released_package_versions(bucket: str, folder: str) -> dict:
    data = subprocess.check_output([f"gsutil ls -lh 'gs://{bucket}/{folder}/' | grep -E '\.whl|\.tar\.gz'"], shell=True)
    # Currently similar strings are correctly parsed:
    # - apache_airflow_providers_cncf_kubernetes-1.0.2rc1-py3-none-any.whl
    # - apache_airflow_providers_cncf_kubernetes-1.0.2+astro+1-py3-none-any.whl
    # - apache_airflow_providers_cncf_kubernetes-1.0.2-py3-none-any.tar.gz
    # - apache_airflow_providers_cncf_kubernetes-1.0.2-py3-none-any.whl
    # Note - platform information is not handled atm.
    pattern = re.compile("([\w\W]+?)  ([\w\W]+?)  gs://([\w\W]+?(?=/))/([\w\W]+?(?=/))/(([\w\W]+?)-(\d+\.\d+\.\d+(rc\d+)?(\+astro\.\d+)?)-py3-none-any(?:\.whl|\.tar\.gz))")
    matches = pattern.findall(data.decode())
    version_to_files = {}
    for match in matches:
        if match[6] not in version_to_files:
            version_to_files[match[6]] = []
        version_to_files[match[6]].append((match[1], match[4]))
    return version_to_files


def get_released_public_package_list(package: str) -> dict:
    url = f"https://pypi.org/pypi/{package}/json"
    response = requests.get(url)
    response.raise_for_status()
    return {release: files for release, files in response.json()["releases"].items()}


def get_custom_package_json(package_info: tuple) -> dict:
    """Generate dict data for a custom package"""
    return {
        "size": "45630",
        "upload_time_iso_8601": package_info[0],
        "url": package_info[1],
        "filename": package_info[1],
    }


def prepare_index_html(releases: dict, custom_packages: dict):
    newline = "\n"

    links = []
    for version, packages in releases.items():
        if version not in custom_packages:
            links.extend([parepare_package_link(version, package) for package in packages])
        else:
            links.extend([parepare_package_link(version, get_custom_package_json(file)) for file in custom_packages[version]])

    # There could be versions that are not published on the public pip index, but we still want to include them.
    # Example - `7.0.0+astro.2`
    remaining_packages_versions = set(custom_packages.keys()) - set(releases)
    for version in remaining_packages_versions:
        links.extend([parepare_package_link(version, get_custom_package_json(file)) for file in custom_packages[version]])

    return (
        f"<!DOCTYPE html>\n"
        f"<html><head><title>Astronomer Python Packages</title></head>\n"
        f"<body><pre>\n"
        f"{newline.join(links)}"
        f"TOTAL: {len(releases)} objects, 16702514 bytes (15.93 MiB)\n"
        f"</pre></body></html>"
    )


def parepare_package_link(version: str, package: dict):
    return (
        f"{int(package['size'])/1000} KiB  {package['upload_time_iso_8601']}  "
        f"<a href=\"{package['url']}\">"
        f"{package['filename']}"
        f"</a>"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog='generate index.html',
        description='generate index.html for a package',
    )
    parser.add_argument("bucket")
    parser.add_argument("folder")
    args = parser.parse_args()

    custom_packages = get_custom_released_package_versions(bucket=args.bucket, folder=args.folder)
    releases = get_released_public_package_list(package=args.folder)
    print(prepare_index_html(releases, custom_packages))
