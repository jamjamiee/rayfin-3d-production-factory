"""Offline SDK contract tests; install requirements-streaming.txt to enable."""

import contextlib
import io
import json
import unittest
from unittest.mock import patch

from src.fonterra_simulator import (
    SalesSimulation, SimulationConfig, publish_event, stream_to_eventstream,
)

try:
    from azure.eventhub import EventData, EventDataBatch, EventHubProducerClient
    from azure.eventhub.exceptions import EventHubError
except ModuleNotFoundError:
    SDK_AVAILABLE = False
else:
    SDK_AVAILABLE = True


@unittest.skipUnless(SDK_AVAILABLE, "Install requirements-streaming.txt for offline Azure SDK tests.")
class StreamingSdkTests(unittest.TestCase):
    def setUp(self):
        simulation = SalesSimulation(SimulationConfig(max_orders=1))
        self.event = next(simulation.events(realtime=True, clock=lambda: 0))

    def test_actual_sdk_message_properties_and_encoding(self):
        class OfflineProducer:
            def create_batch(self, *, partition_key):
                self.partition_key = partition_key
                return EventDataBatch(max_size_in_bytes=1000000, partition_key=partition_key)

            def send_batch(self, batch, *, timeout):
                self.batch = batch

        producer = OfflineProducer()
        publish_event(producer, self.event)
        self.assertEqual(producer.partition_key, self.event["OrderKey"])
        self.assertEqual(len(producer.batch), 1)
        self.assertGreater(producer.batch.size_in_bytes, 0)
        message = EventData(json.dumps(self.event))
        message.message_id = self.event["EventId"]
        message.content_type = "application/json"
        self.assertEqual(message.raw_amqp_message.properties.message_id, self.event["EventId"])
        self.assertEqual(message.raw_amqp_message.properties.content_type, "application/json")

    def test_stream_closes_on_success_send_failure_and_interrupt(self):
        event = self.event
        for error in (None, EventHubError("connection failed"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                closed = []

                class OfflineProducer:
                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        closed.append(True)

                def events(simulation, *, realtime):
                    self.assertTrue(realtime)
                    yield event

                with patch.object(EventHubProducerClient, "from_connection_string", return_value=OfflineProducer()), \
                        patch.object(SalesSimulation, "events", events), \
                        patch("src.fonterra_simulator.publish_event", side_effect=error), \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    if error is None:
                        stream_to_eventstream(SimulationConfig(max_orders=1), "secret-not-printed")
                    else:
                        expected = KeyboardInterrupt if isinstance(error, KeyboardInterrupt) else RuntimeError
                        with self.assertRaises(expected) as raised:
                            stream_to_eventstream(SimulationConfig(max_orders=1), "secret-not-printed")
                        if expected is RuntimeError:
                            self.assertIn(event["EventId"], str(raised.exception))
                    self.assertNotIn("secret-not-printed", output.getvalue())
                    self.assertIn('"events_acknowledged": 1' if error is None else '"events_acknowledged": 0',
                                  output.getvalue())
                self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
