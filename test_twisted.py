from twisted_cut import defer
import queue
import threading


class Test(object):
    def __init__(self):
        self.def_list = list()
        self.lock = threading.Lock()
        self.q = queue.Queue()

    def defer_to_queue(self, f, *args, **kwargs):
        print("Defer to queue: {0}. Args: {1}, kwargs: {2}".format(f, args, kwargs))
        d = defer.Deferred(canceller=self.cancel_queue_cmd_from_deferred)
        cmd = d
        d.addCallback(self.queue_cb, f, *args, **kwargs)
        with self.lock:
            self.q.put(cmd)
        return d

    def cancel_queue_cmd_from_deferred(self, d):
        print("Cancelling {0}".format(d))
        cmd_list = list()
        with self.lock:
            while self.q.empty() is False:
                cmd = self.q.get_nowait()
                if cmd != d:
                    cmd_list.append(cmd)
            for cmd in cmd_list:
                self.q.put(cmd)

    def queue_cb(self, result, f, *args, **kwargs):
        d = defer_to_thread(f, *args, **kwargs)
        d.addCallbacks(self.command_done, self.command_error)
        return d

    def command_done(self, result):
        print("Command done. Result: {0}".format(result))
        return result

    def command_error(self, err):
        print("Command error. Error: {0}".format(err))
        return err

    def process_queue(self):
        try:
            d = self.q.get_nowait()
            d.callback(True)
        except queue.Empty:
            print("Queue empty")


def defer_to_thread(f, *args, **kwargs):
    """
    Run a function in a thread and return the result as a Deferred.
    @param f: The function to call.
    @param *args: positional arguments to pass to f.
    @param **kwargs: keyword arguments to pass to f.
    @return: A Deferred which fires a callback with the result of f,
    or an errback with a L{twisted.python.failure.Failure} if f throws
    an exception.
    """
    def run_thread(df, func, *f_args, **f_kwargs):
        print("Run thread {0}. Args: {1}, kwargs: {2}".format(func, f_args, f_kwargs))
        try:
            result = func(*f_args, **f_kwargs)
            df.callback(result)
        except Exception as e:
            df.errback(e)

    print("Defer to thread: {0}. Args: {1}, kwargs: {2}".format(f, args, kwargs))
    d = defer.Deferred()
    rt_args = (d, f) + args
    t = threading.Thread(target=run_thread, args=rt_args, kwargs=kwargs)
    t.start()
    return d


def test_func(a, b=0):
    print("Test func. a: {0}, b: {1}".format(a, b))


if __name__ == "__main__":
    t = Test()
    d = t.defer_to_queue(test_func, 10, b=20)
