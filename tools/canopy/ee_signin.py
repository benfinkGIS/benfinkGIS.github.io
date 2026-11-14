"""One-time Google Earth Engine sign-in for this computer.

Run:  py tools/canopy/ee_signin.py --project YOUR_PROJECT_ID
      (needs: pip install earthengine-api)

Opens Google's sign-in page in your browser. You choose the account and
approve access there; this script never sees a password. Google's token is
saved in your user folder (~/.config/earthengine/credentials) and reused by
13_surface_temperature.py.

Earth Engine also needs the id of a Google Cloud project that is registered
for Earth Engine. It is shown at the top right of
https://code.earthengine.google.com/ and in the project picker at
https://console.cloud.google.com/ . An account with no registered project can
register one at https://code.earthengine.google.com/register . The id is
tested and saved to tucson-canopy/work/ee_project.txt.

  --project ID      the Cloud project to use
  --skip-signin     the token is already saved; only test and save the project
"""
import argparse

import ee

from common import WORK


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--skip-signin", action="store_true")
    args = ap.parse_args()
    if not args.skip_signin:
        ee.Authenticate(auth_mode="localhost")
        print("signed in", flush=True)
    if not args.project:
        print("Signed in. Run again with --project YOUR_PROJECT_ID --skip-signin")
        return
    try:
        ee.Initialize(project=args.project)
        ee.Number(1).getInfo()
    except Exception as err:
        raise SystemExit("Earth Engine would not start with that project: "
                         + str(err).splitlines()[0])
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "ee_project.txt").write_text(args.project)
    print("Earth Engine works with this project; id saved")


if __name__ == "__main__":
    main()
