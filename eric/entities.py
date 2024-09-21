import asyncio
from threading import Lock

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterable, Any

import eric
from eric.exception import InvalidChannelException, InvalidListenerException, NoMessagesException

logger = eric.get_logger()


@dataclass
class Message:
    """
    Models a message

    It's just a container of information identified by a type.
    For validation purposes you can override MessageQueueListener.on_message
    """
    type: str
    payload: dict | list | str | int | float | None = None


def create_simple_mesage(txt: str) -> Message:
    return Message(type='txt', payload=txt)

class MessageQueueListener(ABC):
    """
    Base class for listeners.

    Optionally you can override on_message method if you need to inject code at message delivery time.
    """
    NEXT_ID = 1

    def __init__(self):
        with Lock():
            self.id: str = str(MessageQueueListener.NEXT_ID)
            MessageQueueListener.NEXT_ID += 1
        self.__is_running: bool = False

    async def start(self) -> None:
        """Starts listening"""
        self.__is_running = True

    def start_sync(self) -> None:
        """Starts listening"""
        self.__is_running = True

    async def is_running(self) -> bool:
        """Returns listener's state: stopped vs. running"""
        return self.__is_running

    def is_running_sync(self) -> bool:
        """Returns listener's state: stopped vs. running"""
        return self.__is_running

    async def stop(self) -> None:
        """Stops listening"""
        self.__is_running = False

    async def stop_sync(self) -> None:
        """Stops listening"""
        self.__is_running = False

    def on_message(self, msg: Message) -> None:
        """
        Event handler. It executes whan a message is delivered to client
        """
        pass

class AbstractChannel(ABC):
    """
    Base class for channels.

    Provides functionalities for listeners and message delivery management.
    SSEChannel is the default implementation
    """
    NEXT_ID = 1

    def __init__(self):
        logger.info(f'Creating channel {AbstractChannel.NEXT_ID}')
        with Lock():
            self.id: str = str(AbstractChannel.NEXT_ID)
            AbstractChannel.NEXT_ID += 1

        self.listeners: dict[str: MessageQueueListener] = {}
        self.queues: dict[str: list[Message]] = {}


    def add_listener(self, l_class: MessageQueueListener.__class__) -> MessageQueueListener:
        """
        DEPRECATED in favor of register_listener. Will be removed from 0.0.4

        Adds a listener to channel

        :param l_class: a valid MessageQueueListener class constructor.
        :return:
        """
        logger.warning('Deprecated method, it will be removed from 0.0.4. Please movw to register_listener')
        l = l_class()
        self.register_listener(l)
        return l

    def register_listener(self, l: MessageQueueListener):
        """
        Adds a listener to channel

        :param l:
        :return:
        """
        self.listeners[l.id] = l
        self.queues[l.id] = []

    def remove_listener(self, l_id: str):
        del self.queues[l_id]
        del self.listeners[l_id]

    def deliver_next(self, listener_id: str) -> Message:
        """
        Returns next message for given listener id.
        Raises a NoMessagesException if queue is empty

        :param listener_id:
        :return:
        """
        if self.get_listener(listener_id).is_running_sync():
            try:
                msg = self.__get_queue(listener_id).pop(0)
                self.get_listener(listener_id).on_message(msg)

                return msg
            except IndexError:
                raise NoMessagesException


    def __get_queue(self, listener_id: str) -> list[Message]:
        try:
            return self.queues[listener_id]
        except KeyError:
            raise InvalidListenerException(f"Invalid listener {listener_id}")


    def dispatch(self, listener_id: str, msg: Message):
        """
        Adds a message to listener's queue

        :param listener_id:
        :param msg:
        :return:
        """
        self._add_to_queue(listener_id, msg)
        logger.debug(f"Pending {len(self.queues[listener_id])} messages")

    def _add_to_queue(self, listener_id: str, msg: Message):
        self.__get_queue(listener_id).append(msg)

    def broadcast(self, msg: Message):
        """
        Enqueue a message to all listeners

        :param msg:
        :return:
        """
        for listener_id in self.listeners.keys():
            self.dispatch(listener_id, msg=msg)


    def get_listener(self, listener_id: str) -> MessageQueueListener:
        try:
            return self.listeners[listener_id]
        except KeyError:
            raise InvalidListenerException

    @abstractmethod
    async def message_stream(self, listener: MessageQueueListener) -> AsyncIterable[Any]:
        """
        Entry point for message streanung.

        :param listener:
        :return:
        """
        ...


class SSEChannel(AbstractChannel):
    """
    SSE streaming channel.
    See https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#event_stream_format

    Currently, 'id' field is not supported.

    In case of failure at channel resulution time, a special message with type='_eric_channel_closed' is sent, and
    correspondant listener is stopped
    """

    def __init__(self, stream_delay_seconds: int = 0, retry_timeout_millisedonds: int = 15000):
        super().__init__()
        self.stream_delay_seconds = stream_delay_seconds
        self.retry_timeout_millisedonds = retry_timeout_millisedonds

    async def message_stream(self, listener: MessageQueueListener) -> AsyncIterable[dict]:

        def new_messages():
            try:
                yield self.deliver_next(listener.id)
            except NoMessagesException:
                ...

        async def event_generator() -> AsyncIterable[dict]:
            while True:
                # If client closes connection, stop sending events
                if not await listener.is_running():
                    break

                try:
                    for message in new_messages():
                        yield {
                            "event": message.type,
                            "retry": self.retry_timeout_millisedonds,
                            "data": message.payload
                        }

                    await asyncio.sleep(self.stream_delay_seconds)
                except InvalidChannelException as e:
                    logger.info(f"Stopping listener {listener.id}")
                    logger.debug(e)
                    await listener.stop()
                    yield {
                        "event": "_eric_channel_closed",
                        "data": None
                    }

        return event_generator()
