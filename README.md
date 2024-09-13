# 🌀 tornado-asgi

A simple adapter to allow running Tornado under ASGI.

## Usage

```python
from .some_where import tornado_app
from tornado_asgi import ASGIAdapter
import uvicorn

# wrapping your tornado app in ASGIAdapter makes it an ASGI app
app = ASGIAdapter(tornado_app)
# run it with uvicorn or any ASGI server
uvicorn.run(app, host="0.0.0.0", port=8000)
```
