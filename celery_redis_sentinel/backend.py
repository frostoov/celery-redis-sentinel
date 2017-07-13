# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

from celery.backends.redis import RedisBackend
from kombu.utils import cached_property
import json
import pickle
from redis import Redis

from .redis_sentinel import EnsuredRedisMixin, get_redis_via_sentinel


class RedisSentinelBackend(RedisBackend):
    """
    Redis results backend with support for Redis Sentinel

    .. note::
        In order to correctly configure the sentinel,
        this backend expects an additional backend celery
        configuration to be present - ``CELERY_RESULT_BACKEND_TRANSPORT_OPTIONS``.
        Here is are sample transport options::

            CELERY_RESULT_BACKEND_TRANSPORT_OPTIONS = {
                'sentinels': [('192.168.1.1', 26379),
                              ('192.168.1.2', 26379),
                              ('192.168.1.3', 26379)],
                'service_name': 'master',
                'socket_timeout': 0.1,
            }
    """

    def __init__(self, transport_options=None, *args, **kwargs):
        super(RedisSentinelBackend, self).__init__(*args, **kwargs)

        _get = self.app.conf.get
        self.transport_options = transport_options or _get('CELERY_RESULT_BACKEND_TRANSPORT_OPTIONS') or {}
        self.sentinels = self.transport_options['sentinels']
        self.service_name = self.transport_options['service_name']
        self.socket_timeout = self.transport_options.get('socket_timeout', 0.1)

    @cached_property
    def client(self):
        """
        Cached property for getting ``Redis`` client to be used to interact with redis.

        Returned client also subclasses from :class:`.EnsuredRedisMixin` which
        ensures that all redis commands are executed with retry logic in case
        of sentinel failover.

        Returns
        -------
        Redis
            Redis client connected to Sentinel via Sentinel connection pool
        """
        params = self.connparams
        params.update({
            'sentinels': self.sentinels,
            'service_name': self.service_name,
            'socket_timeout': self.socket_timeout,
        })
        return get_redis_via_sentinel(
            redis_class=type(str('Redis'), (EnsuredRedisMixin, Redis), {}),
            **params
        )

    def prepare_exception(self, exc, serializer=None):
        exc = self._wrap_exc(exc)
        return super(RedisSentinelBackend, self).prepare_exception(exc, serializer)

    def exception_to_python(self, exc):
        exc = super(RedisSentinelBackend, self).exception_to_python(exc)
        return self._unwrap_exc(exc)

    @staticmethod
    def _wrap_exc(e):
        try:
            return Exception(json.dumps({
                'type': type(e).__name__,
                'module': type(e).__module__,
                'data': e.serialize() if hasattr(e, 'serialize') else pickle.dumps(e),
            }))
        except:
            return e

    @staticmethod
    def _unwrap_exc(e):
        try:
            exc = json.loads(str(e))
            cls = getattr(RedisSentinelBackend._get_module(exc['module']), exc['type'])
            if hasattr(cls, 'deserialize'):
                return cls.deserialize(exc['data'])
            return pickle.loads(exc['data'])
        except:
            return e

    @staticmethod
    def _get_module(module_name):
        from importlib import import_module
        from sys import modules
        from types import ModuleType
        module = modules.get(module_name)
        if isinstance(module, ModuleType):
            return module
        return import_module(module_name)
