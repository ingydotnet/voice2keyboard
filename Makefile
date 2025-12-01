M := .cache/makes
$(shell [ -d $M ] || ( git clone -q https://github.com/makeplus/makes $M))

include $M/init.mk
include $M/python.mk
include $M/clean.mk
include $M/shell.mk

MODEL := $(shell grep ^default_model: config.yaml | cut -f2 -d' ')

VOSK-URL := https://alphacephei.com/vosk/models

MAKES-REALCLEAN := \
	vosk-* \

DEPS := \
  $(PYTHON) \
  $(PYTHON-VENV)/bin/pynput \

SERVICE-FILE := $(HOME)/.config/systemd/user/voice2keyboard.service

export XDG_SESSION_TYPE := x11

key ?= alt_r


run: $(MODEL) $(DEPS)
	TRIGGER_KEY=$(key) python voice2keyboard.py $<

install: $(DEPS) $(SERVICE-FILE)
	systemctl --user daemon-reload
	systemctl --user enable voice2keyboard
	systemctl --user start voice2keyboard
	@echo "voice2keyboard installed and running"
	@echo "Hold Delete key to record and type"

$(SERVICE-FILE): voice2keyboard.service
	mkdir -p $(dir $@)
	sed 's|%h/src/voice2keyboard|$(ROOT)|g' $< > $@

uninstall:
	-systemctl --user stop voice2keyboard
	-systemctl --user disable voice2keyboard
	rm -f $(SERVICE-FILE)
	systemctl --user daemon-reload
	@echo "voice2keyboard uninstalled"

status:
	systemctl --user status voice2keyboard

logs:
	journalctl --user -u voice2keyboard -f

$(PYTHON-VENV)/bin/pynput: $(PYTHON-VENV)
	pip install pynput vosk pyyaml

$(MODEL): $(MODEL).zip
	unzip $<
	touch $@

$(MODEL).zip:
	wget $(VOSK-URL)/$@
