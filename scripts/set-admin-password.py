#!/usr/bin/env python3
"""Create the contents of /volume1/docker/admin-auth/auth.json. Run it yourself: nothing is stored or sent.

    python3 scripts/set-admin-password.py > auth.json

The prompts go to the terminal and only the file's contents go to the output.
This is also the way back in if the password is forgotten.
Running it again logs every device out, because the session key changes too.
"""
import getpass
import json
import os
import secrets
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "stacks", "home"))
import auth  # noqa: E402

first = getpass.getpass("New admin password: ")
if len(first) < auth.MIN_PASSWORD_LEN:
    sys.exit("Use at least 8 characters.")
if getpass.getpass("Again: ") != first:
    sys.exit("The two passwords don't match.")
print(json.dumps({"hash": auth.hash_password(first), "key": secrets.token_hex(32)}))
