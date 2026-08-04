# timeful-cli

An unofficial, dependency-free command-line client for creating and working with [Timeful](https://timeful.app) availability polls.

> [!IMPORTANT]
> This project is not affiliated with or endorsed by Timeful. It uses Timeful endpoints that may change without notice. The CLI never asks for Google or Outlook tokens and never copies cookies from your browser.

## Install

Python 3.10 or newer is required. Install the current release directly from GitHub:

```bash
pipx install git+https://github.com/jaykbpark/timeful-cli.git
```

Or run it without installing:

```bash
uvx --from git+https://github.com/jaykbpark/timeful-cli.git timeful --help
```

## Log in

Timeful supports passwordless email login. The CLI sends a six-digit OTP through Timeful and prompts for it without echoing it to the terminal:

```bash
timeful auth login --email jay@example.com
timeful auth status
```

The resulting Timeful session cookie is stored at `~/.config/timeful-cli/cookies.txt`. On POSIX systems, the directory is restricted to the current user and the cookie file is created with `0600` permissions; Windows relies on the user profile's filesystem ACLs. Set `TIMEFUL_CONFIG_DIR` to choose a different directory.

Log out and remove the local session:

```bash
timeful auth logout
```

Use `--anonymous` before any non-auth command to deliberately ignore the saved login:

```bash
timeful --anonymous create ...
```

## Create an event

Log in first when you want the event associated with your account. This is required for blind polls and for viewing collected guest emails.

```bash
timeful create \
  --name "Coffee chat" \
  --duration 30m \
  --date 2026-08-10T17:00:00Z \
  --date 2026-08-11T18:00:00Z \
  --url-only
```

Useful options include:

- `--blind`: only the authenticated owner can see everyone's responses.
- `--collect-emails`: ask guests for email addresses; only the authenticated owner receives them.
- `--days-only`: poll for whole days.
- `--increment 15|30|60`: choose the response-grid interval.

The CLI refuses to create a blind poll without a working login so you do not accidentally create a poll whose aggregate results you cannot access.

## View results

`results` combines Timeful's event metadata and availability response data into one clean payload containing names, available times, if-needed times, and owner-visible emails:

```bash
timeful results https://timeful.app/e/EVENT_ID
```

The time range is inferred from the event. Override it when needed:

```bash
timeful results EVENT_ID \
  --time-min 2026-08-10T00:00:00Z \
  --time-max 2026-08-12T00:00:00Z
```

The response is structured for both people and scripts:

```json
{
  "event": {
    "id": "...",
    "name": "Coffee chat"
  },
  "responseCount": 2,
  "respondents": [
    {
      "id": "...",
      "name": "Ada Lovelace",
      "availability": ["2026-08-10T17:00:00Z"],
      "ifNeeded": []
    }
  ]
}
```

For the uncombined API payloads, use `timeful show` and `timeful responses`.

## Respond to an event

Respond using your logged-in Timeful identity:

```bash
timeful respond EVENT_ID \
  --as-me \
  --available 2026-08-10T17:00:00Z \
  --if-needed 2026-08-11T18:00:00Z
```

Or respond as a guest:

```bash
timeful respond EVENT_ID \
  --name "Jay" \
  --email jay@example.com \
  --available 2026-08-10T17:00:00Z
```

Repeat `--available` or `--if-needed` for every slot start. Updating a response replaces that identity's previously submitted availability.

## Advanced event payloads

For Timeful options that do not yet have first-class flags, provide the complete request body:

```bash
timeful create --payload-file event.json
```

## Privacy and compatibility

- Treat event IDs and share URLs as access links.
- A non-blind poll allows anyone with the link to read its names and availability.
- A blind poll returns all responses only to its authenticated owner.
- Collected emails are returned only to the authenticated owner.
- The saved session cookie is an account credential. Do not commit, copy, or share it.
- Timeful's service and payload formats remain the source of truth. A backend change may require a CLI update.

Timeful itself is open source and publishes a browser-oriented [Plugin API](https://github.com/schej-it/timeful.app/blob/main/PLUGIN_API_README.md). This CLI talks directly to the same event and authentication service without needing a browser session.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

## License

MIT. Timeful's name and branding belong to their respective owners.
