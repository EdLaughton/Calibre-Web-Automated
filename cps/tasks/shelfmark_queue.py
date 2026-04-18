# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from __future__ import annotations

from flask_babel import lazy_gettext as N_

from cps import logger
from cps.services.worker import CalibreTask

from cps.services.shelfmark_client import ShelfmarkClientError, get_shelfmark_client_config
from cps.services.shelfmark_queue import sync_shelfmark_queue


class TaskShelfmarkQueueSync(CalibreTask):
    def __init__(self, task_message=N_("Syncing Shelfmark queue")):
        super(TaskShelfmarkQueueSync, self).__init__(task_message)
        self.log = logger.create()

    def run(self, worker_thread):
        config_data = get_shelfmark_client_config()
        if not config_data.enabled:
            self._handleSuccess()
            return

        try:
            result = sync_shelfmark_queue(config_data)
            self.log.debug("Shelfmark queue sync complete: %s", result)
            self._handleSuccess()
        except ShelfmarkClientError as exc:
            self.log.warning("Shelfmark queue sync failed: %s", exc)
            self._handleError(str(exc))
        except Exception as exc:
            self.log.error("Unexpected Shelfmark queue sync failure: %s", exc)
            self._handleError(str(exc))

    @property
    def name(self):
        return "Shelfmark Queue Sync"

    @property
    def is_cancellable(self):
        return False

