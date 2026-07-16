"""JELOTIA activation server — issues signed licenses over HTTP.

Runs on JELOTIA's own infrastructure, NOT shipped to customers. A customer's
app posts its machine fingerprint and a purchase token; the server checks the
token, signs a license with the private key it alone holds, and returns it. The
app then installs the license and runs fully offline afterwards.

Deploying and the private key are covered in README.md. Nothing here ever ships
inside the desktop build (fastapi/uvicorn live in the optional `server` group).
"""
