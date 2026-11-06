# Working on the NAS

Read README.md first; it is the source of truth for the setup.

- SSH: `ssh <user>@192.168.1.14` (key login, docker group). Never run root commands through a privileged container; ask the user to run `sudo` steps.
- `scp` can't write to `/volume1`: copy with `ssh … 'cat > file' < local` or `tar | ssh tar`.
- Stacks: `/volume1/docker/<name>/`, mirrored in `stacks/<name>/`. Edit here, copy to the NAS, apply, then run `scripts/sync-from-nas.sh` and commit.
- Never commit `.env`, `data/`, AdGuard `conf/`, AutoBangumi `config/`, or any password/token. Don't print secrets in output.
- Homepage: recreate (not restart) after `.env` changes. Check designs with `scripts/shoot.sh` at 1920×1080, 1800×1125 and 400 px; the user wants calm Apple-HIG style (no nested boxes, one key number per card).
- Ask before anything destructive or hard to undo on the NAS (deleting media, changing UGOS system config, router changes).
- Update README.md (services table, known issues, changelog) with every change.
