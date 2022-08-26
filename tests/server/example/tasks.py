from django_gcp.tasks import PeriodicTask, SubscriberTask, Task


# NOTE: See the following link for a discussion on disabling pylint when overriding the `run` method.
# https://stackoverflow.com/questions/73454704/how-to-define-keyword-variadic-arguments-in-a-notimplementedyet-abc-method-avoi


class BaseAbstractTask(Task):
    """Demonstrates how to create an abstract task class for your own use

    This still inherits from the Task class so can be used to generate other subclasses of Task.
    """

    abstract = True

    def run(self, **_):
        raise NotImplementedError()


class MyOnDemandTask(Task):
    """Demonstrates how to create an on-demand task (by directly inheriting from Task)"""

    def run(self, **kwargs):
        print(
            "Received message from Cloud Tasks on MyOnDemandTask:\n",
            kwargs,
        )


class FailingOnDemandTask(BaseAbstractTask):
    """Demonstrates what happens when a task fails due to an exception in the task
    (also shows inheritance from your custom BaseAbstractTask class)
    """

    deduplicate = True

    def run(self, **kwargs):
        print(
            "Received message from Cloud Tasks on FailingOnDemandTask:\n",
            kwargs,
        )
        return 1 / 0


class MyPeriodicTask(PeriodicTask):
    """Demonstrates how to create a periodic task running on a cron schedule"""

    run_every = "* * * * *"

    def run(self, **kwargs):
        print("Received message from Cloud Scheduler on MyPeriodicTask:\n", kwargs)


class PleaseNotifyMeTask(SubscriberTask):
    """Demonstrates how to create a task that triggers on a message to a particular Pub/Sub topic"""

    enable_message_ordering = True

    @property
    def topic_id(self):
        return "potato"

    def run(self, **kwargs):  # pylint: disable=arguments-differ
        print("Received message from Pub/Sub on PleaseNotifyMeTask:\n", kwargs)
