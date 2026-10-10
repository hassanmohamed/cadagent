# Deploying the Streamlit app

For the developer. The app is `streamlit_app.py` at the root of the repository.

## Run it locally first

```sh
uv sync
uv run streamlit run streamlit_app.py     # opens http://localhost:8501
```

Settings are read from `.env` locally (see `.env.example`).

## Streamlit Community Cloud

1. Push the repository to GitHub. The company owns the code, so use a **private**
   repository.
2. On <https://share.streamlit.io> choose **Create app → Deploy from GitHub**, select the
   repository and branch, and set the main file to `streamlit_app.py`.
3. Under **Advanced settings**, choose **Python 3.12** and paste the secrets:

   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   APP_PASSWORD = "choose-a-password"
   # CADAGENT_MODEL = "claude-opus-5-5"
   ```

4. Deploy. The first build installs the CAD kernel and takes several minutes.

The same template is in `.streamlit/secrets.toml.example`. Never commit a real
`secrets.toml` or `.env`; both are in `.gitignore`.

### Files the platform uses

| File | Purpose |
|---|---|
| `streamlit_app.py` | The app |
| `requirements.txt` | Python packages, pinned to the versions that were tested |
| `packages.txt` | Linux system libraries the CAD kernel needs (OpenGL and X11) |
| `.streamlit/config.toml` | Upload limit (25 MB) and theme |
| `rules/`, `test_data/`, `docs/` | Read by the app at run time |

If the platform installs from `uv.lock` instead of `requirements.txt`, the result is the
same: both list the same versions.

## Settings

| Name | Needed | Effect |
|---|---|---|
| `ANTHROPIC_API_KEY` | For AI reading | Without it the app runs in offline demo mode |
| `APP_PASSWORD` | Recommended when hosted | Shows a password screen before the demo |
| `CADAGENT_MODEL` | No | Use a different Claude model for reading |

## Before sharing the link

- **Set `APP_PASSWORD`.** Without it, anyone with the link can use the app, and every
  Read is paid for with your API key.
- **Check company policy on the drawings.** Uploaded images are sent to Anthropic's API,
  and the app itself runs on Streamlit's servers.
- **Set a spending limit** on the API key in the Anthropic console.

## How the hosted app behaves

- Each browser session has its own part and version history, so several people can use
  it at once.
- Outputs are written to the server's temporary folder. Folders older than 24 hours are
  cleared whenever a new session starts. Nothing is stored permanently: reloading the
  page starts a new session.
- `rules/rules.yaml` is part of the repository. To change the rules on the hosted app,
  commit the change; the app picks it up on the next action.

## Other hosts

Any host that runs a Python 3.12 container works. Install the packages in `packages.txt`
with the system package manager, `pip install -r requirements.txt`, and start with:

```sh
streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0
```

The CAD kernel is large: allow about 2 GB of disk for the install and 1 GB of memory.
