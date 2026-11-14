"""One-time NASA Earthdata sign-in for this computer, for ECOSTRESS data.

Run it yourself in a terminal, not through an assistant:

  py tools/canopy/earthdata_signin.py

It asks for your Earthdata username and password (make a free account first
at https://urs.earthdata.nasa.gov/users/new) and saves them to the .netrc
file in your user folder, where NASA's own tools look for them. Nothing is
sent anywhere but NASA's login service, and nothing is written into this
repository.

Needs: pip install earthaccess
"""
import os
import sys

# a copy installed beside the system Python by an earlier session, if present
extra = os.path.expandvars(r"%TEMP%\finkgeo_pydeps_ea")
if os.path.isdir(extra):
    sys.path.insert(0, extra)

import earthaccess

auth = earthaccess.login(strategy="interactive", persist=True)
if auth.authenticated:
    print("Signed in to NASA Earthdata. The sign-in is saved in your user folder.")
else:
    raise SystemExit("Earthdata did not accept that username and password.")
