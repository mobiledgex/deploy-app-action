#!/usr/local/bin/python

import argparse
import json
import logging
import os
import requests
import sys

logging.basicConfig(format="[%(levelname)s] %(message)s")

def die(msg, rc=2):
    print(f"::error::{msg}")
    sys.exit(rc)

def set_output(name, value):
    print(f"::set-output name={name}::{value}")

def get_version():
    ref = os.getenv('GITHUB_REF')
    if ref == "refs/heads/master":
        return "latest"
    elif ref.startswith("refs/tags/"):
        return ref.split("/")[-1]
    else:
        tokens = ref.split("/")
        version = "-".join(tokens[2:])
        if tokens[1] == "pull":
            version = "pr-" + version
        return version

def load_response(r, stream=False):
    items = r.text.splitlines() if stream else [ r.text ]
    resp = []
    for item in items:
        d = json.loads(item)
        if len(d) == 1 and "data" in d:
            d = d["data"]
        resp.append(d)
    return resp if stream else resp[0]

def get_mc(console, username, password):
    r = requests.post(f"{console}/api/v1/login",
                      json={"username": username, "password": password})
    if r.status_code != requests.codes.ok:
        logging.critical(f"MC login failed: {console}: {r.status_code} {r.text}")
        die(f"Failed to log in to the console: {console}")

    token = r.json()["token"]
    apibase = f"{console}/api/v1/auth"

    def mc(path, method="POST", headers={}, data={}, **kwargs):
        req_hdrs = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        req_hdrs.update(headers)
        if data:
            req_data = data
        else:
            req_data = kwargs

        r = requests.request(method, f"{apibase}/{path}",
                             headers=req_hdrs,
                             json=req_data)
        if r.status_code != requests.codes.ok:
            logging.critical(f"MC call failed: {console} {path}: {r.status_code} {r.text}")
            die(f"MC call failed: {path}, {r.status_code}")

        try:
            resp = load_response(r)
        except Exception:
            # Check if response is a JSON stream
            resp = load_response(r, stream=True)

        return resp

    return mc

def main(args):
    for envvar in ("MOBILEDGEX_USERNAME", "MOBILEDGEX_PASSWORD"):
        if not os.getenv(envvar):
            die(f"Mandatory variable not set: {envvar}")

    version = get_version()
    set_output("version", version)
    set_output("setup", args.setup)

    if args.setup == "main":
        console = "https://console.mobiledgex.net"
    else:
        console = f"https://console-{args.setup}.mobiledgex.net"

    mc = get_mc(console, username=os.getenv("MOBILEDGEX_USERNAME"),
		password=os.getenv("MOBILEDGEX_PASSWORD"))

    # Create App
    mc("ctrl/CreateApp", data={
        "region": args.region,
        "app": {
            "key": {
                "name": args.appname,
                "organization": args.apporg,
                "version": version
            },
            "image_path": args.imagepath,
            "image_type": 1,
            "access_ports": args.accessports,
            "default_flavor": {
                "name": args.defaultflavor
            }
        }
    })

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("appname", help="Name of this app")
    parser.add_argument("apporg", help="Organization the app belongs to")
    parser.add_argument("region", help="Region to deploy to")
    parser.add_argument("imagepath", help="Docker image path")
    parser.add_argument("accessports", help="Access ports")
    parser.add_argument("defaultflavor", help="Default flavor")
    parser.add_argument("--setup", "-s", help="Setup to deploy app to",
                        default="main")
    args = parser.parse_args()

    main(args)
