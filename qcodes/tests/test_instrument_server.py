from unittest import TestCase
import time
import multiprocessing as mp

from qcodes.utils.multiprocessing import SERVER_ERR
from qcodes.instrument.server import InstrumentServer


def schedule(queries, query_queue):
    '''
    queries is a sequence of (delay, args)
    query_queue is a queue to push these queries to, with each one waiting
        its delay after sending the previous one
    '''
    for delay, args in queries:
        time.sleep(delay)
        query_queue.put(args)


def run_schedule(queries, query_queue):
    p = mp.Process(target=schedule, args=(queries, query_queue))
    p.start()
    return p


def get_results(response_queue, error_queue):
    time.sleep(0.05)  # wait for any lingering messages to the queues
    responses, errors = [], []
    while not response_queue.empty():
        responses.append(response_queue.get())
    while not error_queue.empty():
        errors.append(error_queue.get())

    return responses, errors


class Holder:
    def __init__(self, uuid):
        self.uuid = uuid
        self.d = {}

    def get(self, key):
        return self.d[key]

    def set(self, key, val):
        self.d[key] = val

    def get_extras(self):
        return self.server_extras


class TestInstrumentServer(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.query_queue = mp.Queue()
        cls.response_queue = mp.Queue()
        cls.error_queue = mp.Queue()

    @classmethod
    def tearDownClass(cls):
        del cls.query_queue
        del cls.response_queue
        del cls.error_queue

    def test_normal(self):
        # we really only need to test local here - as a server it's already
        # used in other tests, but only implicitly (and not covered as it's
        # in a subprocess)
        holder = Holder('Gr33n 3665 & H4m')

        queries = (
            # add an "instrument" to the server
            (0.5, ('new', holder)),

            # some sets and gets that work
            (0.01, ('write', holder.uuid, 'set',
                    ('happiness', 'a warm gun'), {})),
            (0.01, ('write', holder.uuid, 'set',
                    (), {'val': 42, 'key': 'the answer'})),
            (0.01, ('ask', holder.uuid, 'get', (), {'key': 'happiness'})),
            (0.01, ('ask', holder.uuid, 'get', ('the answer',), {})),

            # then some that make errors
            # KeyError
            (0.01, ('ask', holder.uuid, 'get', ('Carmen Sandiego',), {})),
            # TypeError (too many args)
            (0.01, ('write', holder.uuid, 'set', (1, 2, 3), {})),
            # TypeError (unexpected kwarg)
            (0.01, ('write', holder.uuid, 'set', (), {'c': 'middle'})),

            # and another good one, just so we know it still works
            (0.01, ('ask', holder.uuid, 'get_extras', (), {})),

            # delete the instrument and stop the server
            # (no need to explicitly halt)
            (0.01, ('delete', holder.uuid))
        )
        extras = 'infinity and beyond'

        run_schedule(queries, self.query_queue)

        InstrumentServer(self.query_queue, self.response_queue,
                         self.error_queue, extras)

        responses, errors = get_results(self.response_queue, self.error_queue)

        expected_errors = [
            ('KeyError', 'Carmen Sandiego'),
            ('TypeError', '(1, 2, 3)'),
            ('TypeError', 'middle')
        ]
        self.assertEqual(len(errors), len(expected_errors), errors)
        for error, expected_error in zip(errors, expected_errors):
            for item in expected_error:
                self.assertIn(item, error)

        expected_responses = [
            True,
            'a warm gun',
            42,
            SERVER_ERR, SERVER_ERR, SERVER_ERR,
            extras
        ]
        self.assertEqual(responses, expected_responses)
