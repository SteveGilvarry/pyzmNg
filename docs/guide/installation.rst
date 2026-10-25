Installation
============

.. admonition:: Already installed zmesNg? You probably don't need this page
   :class: important

   If you ran zmesNg's ``install.sh`` and installed the ML hooks, pyzm is
   already installed in ``/opt/zoneminder/venv``. The hooks need pyzm, so the
   installer pulls it in with them. You don't need to install it again.

   You only need this page if you want to:

   - use pyzm without zmesNg, for example to script against the ZoneMinder API
   - add an extra the zmesNg installer leaves out, such as ``serve`` (the
     remote ML server) or ``train`` (the model training UI)
   - run pyzm from a source checkout, or upgrade pyzm on its own
   - add one of the `Optional dependencies`_, such as BirdNET or face
     recognition

   pyzm needs OpenCV, and the zmesNg installer doesn't install it. Follow
   the `OpenCV step in the zmesNg install guide
   <https://zmeventnotificationng.readthedocs.io/en/latest/guides/install_path1.html#opencv-install>`__.

.. important::

   pyzm and zmesNg now install into a **shared Python virtual
   environment** (``/opt/zoneminder/venv`` by default) instead of installing
   globally with ``pip install --break-system-packages``.

   Why the change:

   - Modern Linux distributions (Debian 12+, Ubuntu 23.04+, Fedora 38+)
     mark the system Python as *externally managed* (PEP 668) and actively
     block global pip installs.
   - ``--break-system-packages`` bypasses that protection but can break
     OS tools that depend on the system Python.
   - Multiple ZoneMinder components (pyzm, zmesNg hooks) need
     to share a single Python environment — a dedicated venv gives them
     isolation from the OS while still sharing packages with each other.

Requirements
------------

- Python 3.10 or newer
- Pydantic >= 2.0
- OpenCV 4.13+ (``cv2``) -- required for ML detection features (ONNX YOLO models need 4.13+ for full operator support).
  Darknet models (``.weights`` + ``.cfg``, i.e. YOLOv4/YOLOv3) additionally require OpenCV **4.4 or newer but
  below 5.0**: OpenCV 5.0 removed the Darknet importer. PyPI now serves OpenCV 5 wheels, so install it as
  ``pip install "opencv-contrib-python<5"`` if you use Darknet models. Prefer the ONNX models (YOLOv11,
  YOLOv26) — they are more accurate, faster, and carry no upper OpenCV bound.
- A running ZoneMinder instance (for API features)
- A MySQL driver for the features that read the ZM database directly
  (``pyzm[db]``, also part of ``[ml]`` and ``[full]``). See `Database access`_.

Path A: Install from PyPI
--------------------------

The simplest path — no need to clone the repo. Do **NOT** use this path if you have installed ``opencv-python`` from source
as it will overwrite it. Use the build from source path as we have guardrails to preserve your existing ``opencv-python``

**1. Create the venv** (skip if it already exists, e.g. from zmesNg's
installer):

.. code-block:: bash

   sudo python3 -m venv /opt/zoneminder/venv --system-site-packages
   sudo /opt/zoneminder/venv/bin/pip install --upgrade pip setuptools wheel
   sudo chown -R www-data:www-data /opt/zoneminder/venv

**2. Install pyzm:**

.. code-block:: bash

   # Everything (ZM + ML + detection server + training UI):
   sudo /opt/zoneminder/venv/bin/pip install "pyzm[full]"

   # ML detection + remote server:
   sudo /opt/zoneminder/venv/bin/pip install "pyzm[ml,serve]"

   # ML detection + training UI:
   sudo /opt/zoneminder/venv/bin/pip install "pyzm[ml,train]"

   # ML detection only:
   sudo /opt/zoneminder/venv/bin/pip install "pyzm[ml]"

   # ZM API client plus the database features (no ML):
   sudo /opt/zoneminder/venv/bin/pip install "pyzm[db]"

   # ZM API client only (monitors, events, zones; no ML, no database):
   sudo /opt/zoneminder/venv/bin/pip install pyzm

Path B: Install from source
-----------------------------

Clone the repo first, then use the helper script which handles venv creation,
OpenCV shim, and ownership in one step.

.. code-block:: bash

   git clone https://github.com/ZoneMinder/pyzmNg.git
   cd pyzmNg

   # Everything (ZM + ML + detection server + training UI):
   sudo ./scripts/setup_venv.sh --extras full

   # ML detection + remote server:
   sudo ./scripts/setup_venv.sh --extras ml,serve

   # ML detection only:
   sudo ./scripts/setup_venv.sh --extras ml

   # ZM API client only (monitors, events, zones — no ML):
   sudo ./scripts/setup_venv.sh

   # Custom venv path:
   sudo ZM_VENV=/usr/local/zm/venv ./scripts/setup_venv.sh

If the venv already exists (e.g. created by zmesNg's installer),
the script reuses it and just installs/upgrades pyzm.

**Quick editable install** — if you are making local changes to the pyzm source
and want to test them immediately without re-running the full setup script:

.. code-block:: bash

   sudo /opt/zoneminder/venv/bin/pip install -e .

This installs pyzm in *editable* (development) mode so the venv picks up your
source changes directly.

The script will:

1. Install ``python3-venv`` if it is missing (Debian/Ubuntu/Fedora/CentOS).
2. Create the venv with ``--system-site-packages`` so distro-packaged
   libraries (e.g. OpenCV built from source) are still visible.
3. Register an ``opencv-python`` shim if a source/system OpenCV is already
   importable, preventing pip from overwriting it when installing packages
   like ``ultralytics`` that unconditionally depend on ``opencv-python``.
4. Install pyzm (and any requested extras) into the venv.
5. Set ownership to ``www-data`` (configurable via ``ZM_VENV_OWNER``).

What each extra installs
^^^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 15 85

   * - Extra
     - Additional packages
   * - *(base)*
     - requests, pydantic, dateparser, python-dotenv
   * - ``[db]``
     - PyMySQL
   * - ``[ml]``
     - numpy, Pillow, onnx, Shapely, portalocker, imutils, PyMySQL
   * - ``[serve]``
     - ``[ml]`` deps except PyMySQL + fastapi, uvicorn, python-multipart, PyJWT, PyYAML
   * - ``[train]``
     - ``[ml]`` deps except PyMySQL + ultralytics, streamlit, streamlit-drawable-canvas, st-clickable-images, PyYAML
   * - ``[full]``
     - All of the above (``[db]`` + ``[ml]`` + ``[serve]`` + ``[train]``)

.. _db-access:

Database access
^^^^^^^^^^^^^^^

A few features read the ZM database directly instead of going through the
API, so they need a MySQL driver:

- writing to ZM's ``Logs`` table, and reading the ``ZM_LOG_LEVEL_*``
  settings from it (see :doc:`logging`)
- ``ev.tag()``, ``ev.path()`` and ``ev.save_objdetect()`` without
  ``path_override`` (see :doc:`zm_events`)
- audio extraction for BirdNET (see :doc:`detection`)

The ``[db]`` extra installs PyMySQL, a pure Python driver with no
dependencies of its own. ``[ml]`` and ``[full]`` include it, so the zmesNg
hooks have it. If ``mysql-connector-python`` is installed, pyzm uses that
instead. Most installs upgraded from pyzm 2.5.4 or older have it, since it
used to be a base dependency.

Without a driver, the API features work as before. ``ev.tag()``,
``ev.path()`` and BirdNET audio return the same "unavailable" result they
give when the database can't be reached, and pyzm logs
``No MySQL driver installed, DB access unavailable. Install it with: pip install "pyzm[db]"``.

Two PyMySQL setups need one more package:

- MySQL 8 accounts on the default ``caching_sha2_password`` auth, connected
  over TCP without TLS, need ``cryptography`` (``pip install cryptography``).
  You can also point ``ZM_DB_HOST`` at the socket instead, e.g.
  ``localhost:/run/mysqld/mysqld.sock``. MariaDB, which most ZoneMinder
  installs use, doesn't need it.
- MariaDB accounts on ``ed25519`` auth need ``PyNaCl``.

When a connection fails, pyzm logs the driver's error, for example
``DB connect to localhost failed: 'cryptography' package is required for
sha256_password or caching_sha2_password auth methods``.

.. note::

   The ``[train]`` extra pulls in ``ultralytics``, which unconditionally
   requires ``opencv-python`` from PyPI — even if you already have OpenCV
   installed from source or your system package manager.

   The install script (``scripts/setup_venv.sh`` and zmesNg's
   ``install.sh``) attempts to work around this by creating a compatibility
   shim: if ``cv2`` is already importable when the venv is created, a fake
   ``opencv-python`` dist-info entry is registered so that pip considers the
   requirement satisfied and skips the download.

   If your source-built OpenCV is nevertheless overwritten, you can fix it
   manually:

   .. code-block:: bash

      /opt/zoneminder/venv/bin/pip uninstall opencv-python opencv-python-headless
      # Reinstall or rebuild your custom OpenCV — see below

Building OpenCV from source
^^^^^^^^^^^^^^^^^^^^^^^^^^^

The pip ``opencv-python`` package is CPU-only. For GPU-accelerated inference
you need to build OpenCV from source:

- `Apple Silicon (macOS) <https://gist.github.com/pliablepixels/d0605aab085592e1d3b6bb9033bdc835>`_
- `Ubuntu 24.04 with CUDA <https://gist.github.com/pliablepixels/73d61e28060c8d418f9fcfb1e912e425>`_

The venv is created with ``--system-site-packages``, so a system-wide OpenCV
built from source is automatically visible inside the venv.

macOS (development)
-------------------

On macOS the venv can live anywhere — there is no ``www-data`` user:

.. code-block:: bash

   python3 -m venv ~/zm-venv --system-site-packages
   ~/zm-venv/bin/pip install -e ".[ml,serve,train]"

Upgrading
---------

**PyPI install:**

.. code-block:: bash

   # Replace [full] with whichever extras you originally installed:
   sudo /opt/zoneminder/venv/bin/pip install --upgrade "pyzm[full]"

**Source install:**

.. code-block:: bash

   cd pyzmNg
   git pull
   sudo ./scripts/setup_venv.sh --extras full   # same extras you used before

**Upgrading from 2.5.4 or older:** ``mysql-connector-python`` is no longer a
base dependency, but pip doesn't remove it on upgrade, and pyzm keeps using
it while it's installed. You don't need to change anything. To switch to
PyMySQL and free the space (about 70MB), install the ``[db]`` extra (or
``[ml]``/``[full]``, which include it), then remove the old driver if nothing
else in that venv uses it. zmesNg's ``install.sh`` does this for you, after
checking that PyMySQL can connect to your ZM database. To do it by hand:

.. code-block:: bash

   sudo /opt/zoneminder/venv/bin/pip install --upgrade "pyzm[db]"
   sudo /opt/zoneminder/venv/bin/pip uninstall mysql-connector-python

Optional dependencies
---------------------

Some ML backends have additional requirements that are **not** installed
automatically:

- **BirdNET audio recognition** -- ``birdnet-analyzer`` for identifying bird species from audio in ZM events
- (DEPRECATED) **Coral EdgeTPU** -- ``pycoral`` and the Edge TPU runtime
- **Face recognition (dlib)** -- ``dlib``, ``face_recognition``
- **ALPR** -- a running OpenALPR or Plate Recognizer service
- **AWS Rekognition** -- ``boto3`` with configured AWS credentials

Install these into the venv as needed for your detection pipeline:

.. code-block:: bash

   /opt/zoneminder/venv/bin/pip install birdnet-analyzer  # BirdNET audio

**Face recognition (dlib)** — takes a while and installs a lot of dependencies,
which is why it is not included automatically:

.. code-block:: bash

   sudo apt-get install libopenblas-dev liblapack-dev libblas-dev  # not mandatory, but gives a good speed boost
   /opt/zoneminder/venv/bin/pip install face_recognition            # installs dlib automatically

.. note::

   If you use Google Coral, you can do face *detection* (not recognition) via
   the Coral libraries and can skip this section.

If you installed ``face_recognition`` earlier **without** the BLAS libraries,
reinstall both ``dlib`` and ``face_recognition`` so dlib is built with OpenBLAS
support:

.. code-block:: bash

   /opt/zoneminder/venv/bin/pip uninstall dlib face-recognition
   sudo apt-get install libopenblas-dev liblapack-dev libblas-dev   # the important part
   /opt/zoneminder/venv/bin/pip install dlib --verbose --no-cache-dir  # make sure it finds openblas
   /opt/zoneminder/venv/bin/pip install face_recognition

.. note::

   Google has discontinued the Coral EdgeTPU product line and the
   ``pycoral`` library is no longer maintained. Installing it on modern
   Python (3.10+) and recent Linux distributions requires manual
   workarounds. See `pycoral#149
   <https://github.com/google-coral/pycoral/issues/149>`_ for
   community discussion and installation tips.

Verifying the installation
--------------------------

.. code-block:: bash

   # Base install (ZM API client):
   /opt/zoneminder/venv/bin/python -c "import pyzm; print(pyzm.__version__)"

   # ML detection (requires pyzm[ml]):
   /opt/zoneminder/venv/bin/python -c "from pyzm import Detector; print('ML OK')"

   # Database access (run as the ZM user so zm.conf is readable):
   sudo -u www-data /opt/zoneminder/venv/bin/python -c "from pyzm.zm.db import get_zm_db; print('DB OK' if get_zm_db() else 'DB unavailable')"

To verify the training UI is available:

.. code-block:: bash

   /opt/zoneminder/venv/bin/python -c "from pyzm.train import check_dependencies; check_dependencies(); print('OK')"
