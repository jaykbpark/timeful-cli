# timeful-cli

An unofficial, dependency-free command-line client for creating and working with public [Timeful](https://timeful.app) availability polls.

> [!IMPORTANT]
> This project is not affiliated with or endorsed by Timeful. It uses public event endpoints that may change without notice. It intentionally does not accept account cookies, tokens, or other login credentials.

## Install

Python 3.10 or newer is required. Install the current release directly from GitHub:

```bash
pipx install git+https://github.com/jaykbpark/timeful-cli.git
```

Or run it without installing:

```bash
uvx --from git+https://github.com/jaykbpark/timeful-cli.git timeful --help
```

## Quick start

Create an anonymous event and print its share URL:

```bash
timeful create \
  --name "Coffee chat" \
  --duration 30m \
  --date 2026-08-10T17:00:00Z \
  --date 2026-08-11T18:00:00Z \
  --url-only
```

Read a public event. Both an ID and a full share URL work:

```bash
timeful show EVENT_ID
timeful show https://timeful.app/e/EVENT_ID
```

Read responses when the event's privacy settings allow it:

```bash
timeful responses EVENT_ID \
  --time-min 2026-08-10T00:00:00Z \
  --time-max 2026-08-12T00:00:00Z
```

Set guest availability by repeating `--available` or `--if-needed` for each slot start:

```bash
timeful respond EVENT_ID \
  --name "Jay" \
  --available 2026-08-10T17:00:00Z \
  --available 2026-08-10T17:15:00Z \
  --if-needed 2026-08-11T18:00:00Z
```

Every command emits JSON by default, making the CLI easy to use with `jq` and shell scripts.

## Advanced event payloads

For Timeful options that do not yet have first-class flags, provide the complete request body:

```bash
timeful create --payload-file event.json
```

The CLI never stores credentials or event data locally.

## Privacy and compatibility

- Event IDs and share URLs should be treated as access links.
- Public response data may include names or email addresses depending on the event settings. Be careful when saving or piping it elsewhere.
- Guest response updates overwrite that guest's submitted availability.
- Timeful's service and payload formats remain the source of truth. A backend change may require a CLI update.

Timeful itself is open source and publishes a browser-oriented [Plugin API](https://github.com/schej-it/timeful.app/blob/main/PLUGIN_API_README.md). This CLI talks directly to the public event endpoints used by the web application so it can work without a browser session.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

## License

MIT. Timeful's name and branding belong to their respective owners.
