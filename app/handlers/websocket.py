import weakref

from concurrent.futures import ThreadPoolExecutor
from tornado import gen
from tornado.ioloop import IOLoop
from tornado.iostream import StreamClosedError
from tornado.httputil import HTTPServerRequest
from tornado.web import Application
from tornado.websocket import WebSocketHandler, WebSocketClosedError

from ..system import system_data
from ..network import network_data
from .base import workers

# Create a thread pool executor
executor = ThreadPoolExecutor(max_workers=16)


class WebsocketHandler(WebSocketHandler):
    """
    WebSocketHandler that handles WebSocket connections and communicates with
    system and network data sources.

    Attributes:
        loop (IOLoop): The current IOLoop instance.
        worker_ref (weakref.ref): A weak reference to the worker associated
            with this WebSocket connection.
    
    Methods:
        data_received(chunk: bytes): Receives data chunks (no operation in this handler).
        check_origin(origin: str): Checks the origin of the request (always allows connections).
        open(): Handles the opening of a WebSocket connection.
        monitor(): Coroutine that continuously sends system data to the client.
        network(): Coroutine that continuously sends network data to the client.
        on_message(message: str): Handles incoming messages from the WebSocket client.
        on_close(): Cleans up and closes the associated worker when the connection closes.
    """


    def __init__(self, application: Application, request: HTTPServerRequest, **kwargs):
        """
        Initializes the WebSocketHandler.

        Args:
            application (Application): The Tornado Application instance.
            request (HTTPServerRequest): The HTTPServerRequest object for this WebSocket connection.
            **kwargs: Additional keyword arguments to pass to the base class initializer.
        """

        self.loop = IOLoop.current()
        self.worker_ref = None
        super().__init__(application, request, **kwargs)


    def check_origin(self, origin: str):
        """
        Checks whether the WebSocket connection origin is allowed.

        Args:
            origin (str): The origin of the WebSocket request.

        Returns:
            bool: Always returns True, allowing connections from any origin.
        """

        return True


    def open(self):
        """
        Handles the opening of a WebSocket connection. Retrieves the worker based on the 'id'
        argument, sets the worker for this handler, and starts the monitoring coroutine.
        """

        worker = workers.pop(self.get_argument('id'), None)

        if not worker:
            self.close(reason='Invalid worker id')
            return

        self.set_nodelay(True)

        worker.set_handler(self)
        self.worker_ref = weakref.ref(worker)

        self.write_message('connected to monitor, transmitting data...')
        IOLoop.current().add_callback(self.monitor)


    async def monitor(self):
        """
        Coroutine that continuously retrieves system data using a thread pool executor
        and sends it to the WebSocket client. Closes the connection if an error occurs
        or when the WebSocket is closed.
        """

        try:
            while True:
                data = await IOLoop.current().run_in_executor(executor, system_data)
                if data:
                    await self.write_message(data)
        except (StreamClosedError, WebSocketClosedError):
            pass
        finally:
            self.close()


    async def network(self):
        """
        Coroutine that continuously retrieves network data using asynchronous methods
        and sends it to the WebSocket client. Closes the connection if an error occurs
        or when the WebSocket is closed.
        """

        try:
            while True:
                data = await network_data()
                await self.write_message(data)
        except StreamClosedError:
            pass
        except WebSocketClosedError:
            pass
        finally:
            self.close()


    def on_message(self, message: str):
        """
        Handles incoming messages from the WebSocket client.

        Args:
            message (str): The message received from the client.

        Sends a confirmation message back to the client.
        """

        self.write_message('message received %s' % message)


    def on_close(self):
        """
        Handles the closing of the WebSocket connection. Cleans up and closes
        the associated worker if it exists.
        """

        worker = self.worker_ref() if self.worker_ref else None

        if worker:
            worker.close()        