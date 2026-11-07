#!/usr/bin/env python3
"""Create the contents of /volume1/docker/admin-auth.env. Run it yourself: nothing is stored or sent.

    python3 scripts/set-admin-password.py > admin-auth.env

The prompts go to the terminal and only the two settings go to the output.
Running it again logs every device out, because the session key changes too.
"""
import getpass
import os
import secrets
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "stacks", "home"))
import auth  # noqa: E402

first = getpass.getpass("New admin password: ")
if len(first) < 8:
    sys.exit("Use at least 8 characters.")
if getpass.getpass("Again: ") != first:
    sys.exit("The two passwords don't match.")
print(f"ADMIN_PASSWORD_HASH={auth.hash_password(first)}")
print(f"SESSION_SECRET={secrets.token_hex(32)}")
