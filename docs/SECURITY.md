# Credentials, data and public-demo boundaries

## Visitor-owned Groq keys

The sidebar accepts a masked key and keeps it in server memory associated with that Streamlit browser session. The input form clears on submission. `PersonalAI` uses Pydantic `SecretStr` to avoid accidental representation of the value. The app does not write the visitor key to `.env`, SQLite, the audit log, command bodies, a global cache or the repository. Its temporary Groq client is closed after each explicit request.

The key travels over the browser-to-Space HTTPS connection, then authorizes a request from the server to Groq. The Space operator controls the server: this is server-memory isolation, not client-only storage or protection from a malicious host. Use only deployments you trust. Remove the key when finished; the server may retain disconnected session state briefly until Streamlit cleans it up. Reloading or reconnecting can reset session state.

Only selected synthetic evidence and retrieved demo procedures are sent on an explicit request. User keys and generated responses are not visible to other browser sessions. The public launcher clears an inherited `GROQ_API_KEY`, forces the engine AI provider off and never loads a host key into the visitor path. No key is needed for core CPU functions.

## Shared state and authorization

The Space is one shared synthetic exercise. Visitors can start scenarios, pause playback and acknowledge demo reviews for all viewers. Private keys do not imply private simulations. Do not ingest operational data or offer this deployment as an authenticated emergency-response service.

The public port is Streamlit 7860. The API binds to loopback on 8000 and uses independently generated sensor/operator/viewer tokens. These are service credentials, not public-user authentication. Streamlit's default XSRF/CORS protections remain enabled. Do not expose engine port 8000 publicly or add credentials to URL query strings.

## Repository and image hygiene

`.gitignore` excludes `.env`, alternate local env files, virtual environments, runtime state, SQLite files and Streamlit secrets. `scripts.prepare_space` makes a separate allowlisted upload folder and refuses to overwrite an existing one. Upload that folder, not the working directory.

The release-check script scans selected source files for credential patterns and reports filenames without printing matched values. Automated scans reduce accidental publication risk; they cannot prove an arbitrary historic repository contains no secret. If a real secret was ever pushed, revoke it and handle repository history separately. This release process does not rewrite history.

## Failure behavior

SDK retries are disabled. Cooldowns and local limits prevent accidental repeat calls. Error messages do not include raw provider exception bodies or keys. Returned prose must satisfy the AI schema and reference only supplied evidence/procedures; suggested evidence actions must be eligible. Semantic changes during generation discard the private result. This validation constrains structure and references, not the factual correctness of every generated sentence; the operator still reviews it.

The engine and motion model continue when Groq is absent, unavailable or rate limited. Old observations become stale/lost, and movement hypotheses are withheld when input is inadequate. The app sends no vessel-control, dispatch, email or messaging commands.

## Storage lifecycle

SQLite history is local to the running Space instance. Hugging Face Space storage is ephemeral unless external persistence is configured. Restart/rebuild can lose exercises. No persistent storage is required for this demonstration; public visitor keys must not be added to persistence.
