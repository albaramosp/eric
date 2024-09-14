from eric.model import SSEChannel, InvalidChannelException


class Eric:

    def __init__(self):
        self.channels: dict[str: SSEChannel] = {}

    def register_channel(self, channel_id: str) -> SSEChannel:
        if channel_id not in self.channels:
            c = SSEChannel()
            self.channels[channel_id] = c
            return c
        else:
            raise InvalidChannelException

    def delete_channel(self, channel_id: str):
        del self.channels[channel_id]

    def get_channel(self, channel_id: str) -> SSEChannel:
        try:
            return self.channels[channel_id]
        except KeyError:
            raise InvalidChannelException