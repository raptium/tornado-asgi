from tornado.web import Application, RequestHandler

from tornado_asgi.adapter import TornadoASGIAdapter


class MainHandler(RequestHandler):
    def get(self):
        self.write("Hello, world")


app = Application(
    [
        (r"/", MainHandler),
    ]
)

asgi_app = TornadoASGIAdapter(app)

if __name__ == "__main__":
    import uvicorn
    import logging

    logging.basicConfig(level=logging.DEBUG)

    uvicorn.run(asgi_app, host="0.0.0.0", port=8000, log_level="debug")
