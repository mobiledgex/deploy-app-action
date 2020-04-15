#!/usr/local/bin/python

import argparse
import json
import logging
import os
import requests
import sys
import yaml

field_map = (
    (lambda x: x["image_path"], "4"),
    (lambda x: x["access_ports"], "7"),
    (lambda x: x["default_flavor"]["name"], "9"),
)

def get_logger():
    class GithubActionFormatter(logging.Formatter):
        def format(self, rec):
            if rec.levelname in ("DEBUG", "WARNING", "ERROR"):
                msg = f"::{rec.levelname.lower()} " \
                      f"file={rec.filename},line={rec.lineno}::{rec.msg}"
                return msg.replace("\n", "|")
            else:
                return super(GithubActionFormatter, self).format(rec)

    logger = logging.getLogger(__file__)
    ch = logging.StreamHandler()
    formatter = GithubActionFormatter("[%(levelname)s] %(message)s")
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    if os.getenv("ACTIONS_STEP_DEBUG") == "true":
        logger.setLevel(logging.DEBUG)

    return logger

def die(msg, rc=2):
    print(f"::error::{msg}")
    sys.exit(rc)

def set_output(name, value):
    print(f"::set-output name={name}::{value}")

def get_image_revision():
    ref = os.getenv('GITHUB_REF')
    if ref == "refs/heads/master":
        return "latest"
    elif ref.startswith("refs/tags/"):
        return ref.split("/")[-1]
    else:
        tokens = ref.split("/")
        imagerev = "-".join(tokens[2:])
        if tokens[1] == "pull":
            imagerev = "pr-" + imagerev
        return imagerev

def app_diff(oldapp, newapp):
    fields = []
    for (field, field_id) in field_map:
        if field(oldapp) != field(newapp):
            fields.append(field_id)

    return fields

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
        logger.critical(f"MC login failed: {console}: {r.status_code} {r.text}")
        die(f"Failed to log in to the console: {console}")

    token = r.json()["token"]
    apibase = f"{console}/api/v1/auth"

    def mc(path, method="POST", headers={}, data={},
           success_codes=[requests.codes.ok], **kwargs):
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
        if r.status_code not in success_codes:
            logger.critical(f"MC call failed: {console} {path}: {r.status_code} {r.text}")
            die(f"MC call failed: {path}, {r.status_code}")

        try:
            resp = load_response(r)
        except Exception:
            # Check if response is a JSON stream
            resp = load_response(r, stream=True)

        return resp

    return mc

def check_status(resp):
    success = True
    if isinstance(resp, list):
        for item in resp:
            if "message" in item:
                logger.debug(item["message"])
            if "result" in item:
                code = int(item["result"].get("code"))
                if code != requests.codes.ok:
                    logger.error(item["result"].get("message") or f"Error: {code}")
                    success = False
                else:
                    logger.debug(item["result"].get("message"))
    return success

logger = get_logger()

def main(args):
    actions = []
    deployments = []
    for envvar in ("INPUT_USERNAME", "INPUT_PASSWORD"):
        if not os.getenv(envvar):
            die(f"Mandatory variable not set: {envvar}")

    if not os.path.exists(args.appconfig):
        raise Exception(f"App instance definition not found: {args.appconfig}")

    with open(args.appconfig) as f:
        app = yaml.load(f, Loader=yaml.Loader)

    try:
        region = app["region"]
        app_key = app["app"]["key"]
        image_path = app["app"]["image_path"]
        if ":" not in image_path:
            image_rev = get_image_revision()
            app["app"]["image_path"] = f"{image_path}:{image_rev}"
    except Exception as e:
        raise Exception(f"Failed to load app definition: {e}")

    set_output("setup", args.setup)
    set_output("image", app["app"]["image_path"])

    if args.setup == "main":
        console = "https://console.mobiledgex.net"
    else:
        console = f"https://console-{args.setup}.mobiledgex.net"

    mc = get_mc(console, username=os.getenv("INPUT_USERNAME"),
		password=os.getenv("INPUT_PASSWORD"))

    # Check if app exists
    existing_app = mc("ctrl/ShowApp", data={
        "region": region,
        "app": { "key": app_key },
    })

    if existing_app:
        logger.info(f"Updating existing app: {app_key}")
        action = "UpdateApp"
        app["app"]["fields"] = app_diff(existing_app, app["app"])
    else:
        logger.info(f"Creating new app: {app_key}")
        action = "CreateApp"

    # Create/update app
    actions.append(action)
    mc(f"ctrl/{action}", data=app)

    if os.path.exists(args.appinstsconfig):
        with open(args.appinstsconfig) as f:
            appinsts = yaml.load(f, Loader=yaml.Loader)

        for appinst in appinsts:
            try:
                appinst["region"] = region
                appinst["appinst"]["key"]["app_key"] = app_key
                clusterinst_key = appinst["appinst"]["key"]["cluster_inst_key"]
                cluster_name = clusterinst_key["cluster_key"]["name"]
                cluster_org = clusterinst_key.get("organization", app_key["organization"])
                cloudlet_name = clusterinst_key["cloudlet_key"]["name"]
                cloudlet_org = clusterinst_key["cloudlet_key"]["organization"]
            except Exception as e:
                raise Exception(f"Failed to load app instances definition: {e}")

            existing_appinst = mc("ctrl/ShowAppInst", data=appinst)
            if existing_appinst:
                logger.info(f"Updating app instance {cluster_name},{cluster_org} @ {cloudlet_name},{cloudlet_org}")
                resp = mc("ctrl/RefreshAppInst", data=appinst)
                if check_status(resp):
                    logger.debug(f"Updated app inst {cluster_name},{cluster_org} @ {cloudlet_name},{cloudlet_org}")
            else:
                logger.info(f"Creating new app instance {cluster_name},{cluster_org} @ {cloudlet_name},{cloudlet_org}")
                resp = mc("ctrl/CreateAppInst", data=appinst)
                if check_status(resp):
                    logger.debug(f"Created app inst {cluster_name},{cluster_org} @ {cloudlet_name},{cloudlet_org}")

            deployments.append(f"{cloudlet_name}:{cloudlet_org}:{cluster_name}:{cluster_org}")

    set_output("actions", ",".join(actions))
    set_output("deployments", ",".join(deployments))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--appconfig", help="Path to app config",
                        default=".mobiledgex/app.yml")
    parser.add_argument("--appinstsconfig", help="Path to app instances config",
                        default=".mobiledgex/appinsts.yml")
    parser.add_argument("--setup", "-s", help="Setup to deploy app to",
                        default="main")
    args = parser.parse_args()

    main(args)
