R := https://github.com/makeplus/makes
M := .cache/makes
$(shell [ -d '$M' ] || git clone -q $R '$M')

# Use Python 3.13 (3.14 has compatibility issues with faster-whisper)
PYTHON-VERSION ?= 3.13.1

include $M/init.mk
include $M/python.mk
include $M/clean.mk
include $M/shell.mk
include $M/agents.mk

MODEL := $(shell grep ^model: config.yaml | head -1 | cut -f2 -d' ' | tr -d ' ')
MODEL ?= base.en

VOSK-URL := https://alphacephei.com/vosk/models

MAKES-CLEAN := \
  laptalk-log.txt \

MAKES-REALCLEAN := \
  vosk-* \
  .whisper-model-downloaded \
  __pycache__/ \
  .packages-installed \
  .whisper-packages-installed \
  out.txt \

# Base dependencies (Python and packages)
DEPS := \
  $(PYTHON) \
  $(PYTHON-VENV)/bin/pynput \

# Install target uses whisper (as set in service file)
INSTALL_DEPS := $(DEPS) $(PYTHON-VENV)/bin/faster_whisper .whisper-model-downloaded

SERVICE-FILE := $(HOME)/.config/systemd/user/laptalk.service

export XDG_SESSION_TYPE := x11

# Make variables for run target (override from command line)
model ?=
key ?=
mode ?=
pause ?=
log ?=
config ?=

# Build command-line arguments
RUN_ARGS :=
ifneq ($(model),)
  RUN_ARGS += --model=$(model)
  EFFECTIVE_MODEL := $(model)
else
  EFFECTIVE_MODEL := $(MODEL)
endif
ifneq ($(key),)
  RUN_ARGS += --key=$(key)
endif
ifneq ($(mode),)
  RUN_ARGS += --mode=$(mode)
endif
ifneq ($(pause),)
  RUN_ARGS += --pause=$(pause)
endif
ifneq ($(log),)
  RUN_ARGS += --log=$(log)
endif
ifneq ($(config),)
  RUN_ARGS += --config=$(config)
endif

# Infer engine from model name
INFERRED_ENGINE := $(if $(findstring vosk-,$(EFFECTIVE_MODEL)),vosk,whisper)

run: $(DEPS)
ifeq ($(INFERRED_ENGINE),vosk)
	@$(MAKE) -s $(EFFECTIVE_MODEL)
endif
ifeq ($(INFERRED_ENGINE),whisper)
	@$(MAKE) -s $(PYTHON-VENV)/bin/faster_whisper .whisper-model-downloaded
endif
	python laptalk.py $(RUN_ARGS)

help: $(DEPS)
	@echo
	@python laptalk.py --help

install: $(INSTALL_DEPS) $(SERVICE-FILE)
	systemctl --user daemon-reload
	systemctl --user enable laptalk
	systemctl --user start laptalk
	@echo "laptalk installed and running"
	@echo "Hold Alt_R to record and type (using Whisper engine)"

$(SERVICE-FILE): laptalk.service
	mkdir -p $(dir $@)
	sed 's|%h/src/laptalk|$(ROOT)|g' $< > $@

uninstall:
	-systemctl --user stop laptalk
	-systemctl --user disable laptalk
	rm -f $(SERVICE-FILE)
	systemctl --user daemon-reload
	@echo "laptalk uninstalled"

status:
	systemctl --user status laptalk

logs:
	journalctl --user -u laptalk -f

$(PYTHON-VENV)/bin/pynput: $(PYTHON-VENV)
	@pip install -q --disable-pip-version-check pynput pyyaml vosk watchdog

$(PYTHON-VENV)/bin/faster_whisper: $(PYTHON-VENV)
	@pip install -q --disable-pip-version-check faster-whisper numpy

.whisper-model-downloaded: $(PYTHON-VENV)/bin/faster_whisper
	python -c "from faster_whisper import WhisperModel; WhisperModel('$(if $(model),$(model),$(MODEL))')"
	touch $@

# Vosk model download rules (pattern rules for any vosk-model-*)
vosk-model-%: vosk-model-%.zip
	unzip $<
	touch $@

vosk-model-%.zip:
	wget $(VOSK-URL)/$@
