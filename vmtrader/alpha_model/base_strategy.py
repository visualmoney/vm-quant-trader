"""
The hook surface a strategy author writes against.

'AlphaModel' stays what it has always been: one method that turns a
timestamp into weights. Strategies that only need that keep
subclassing it and nothing here concerns them.

What this adds is somewhere to react to what the venue did. A
strategy that wants to know its order filled has, until now, had
nowhere to be told -- the engine's only question was "what are your
weights". The hooks are the answer to "and what would you like to
know", and they are all no-ops, so overriding none of them costs
nothing.

The executor is not a base class of this. A strategy is handed to an
executor, never derived from one, so nothing here exposes 'start',
'join' or a queue to someone writing a moving-average crossover.

See docs/dev/threading-and-event-architecture.md, decision 1.
"""

from vmtrader.alpha_model.alpha_model import AlphaModel


class BaseStrategy(AlphaModel):
    """
    An AlphaModel that can also be told what happened.

    Subclasses implement '__call__' as before and override whichever
    hooks they care about. Every hook is called on the executor's
    thread, one at a time, in the order the facts arrived -- so a hook
    may take as long as it likes without the broker missing anything,
    and two hooks never run at once.

    Two rules hold inside every hook, and both come from the executor
    owning no account state:

    1. Do not touch the portfolio, and do not ask the broker about it.
       Anything needed arrives in the event.
    2. Do not wait for a reply to anything sent from here. The thread
       that would produce the reply is the one running this hook.
    """

    def on_start(self):
        """
        Called once before any event is handled.

        Somewhere to open a file or warm a cache. It is not where
        account state is read; there is none to read.
        """

    def on_fill(self, event):
        """
        Called when an increment of an order has been booked.

        Already booked, not about to be: the portfolio has the shares
        before this runs. Acting on it means sending a new order, not
        correcting anything.

        Parameters
        ----------
        event : `OrderFilled`
            What filled, how much of it, and at what running average.
        """

    def on_stop(self):
        """
        Called once after the last event, on the way down.

        Not guaranteed. The executor's thread is a daemon, so a
        shutdown that runs out of patience will cut it; anything that
        must survive belongs in a durable store as it happens, not
        here.
        """
