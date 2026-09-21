SHELL   := $(shell which bash)
MODELRE := ^\?\? model/?$
TAG     := ghcr.io/maddenp-cu/aigfs:latest
TARGETS := bootstrap container deploy devenv docs env format lint push rmenv test typecheck unittest

check = @$(if $(1),,$(error $(2)= argument required))

.PHONY: $(TARGETS)

all:
	$(error Valid targets are: $(TARGETS))

bootstrap:
	@bin/run bootstrap

container:
	@git status --ignored --porcelain | egrep -q "$(MODELRE)" || (echo "Missing model/ directory." && false)
	@git status --ignored --porcelain | egrep -v "$(MODELRE)" && echo "Clone must be clean." && exit 1 || true
	podman build --platform linux/amd64,linux/arm64 --manifest $(TAG) --file etc/oci/Containerfile .

deploy:
	$(call check,$(playbook),playbook)
	@bin/run deploy $(playbook)

devenv:
	@bin/run makeenv dev

docs:
	@bin/run makedocs

env:
	@bin/run makeenv

format:
	@bin/run format

lint:
	@bin/run lint

push:
	podman manifest push --all $(TAG) docker://$(TAG)

rmenv:
	@bin/run rmenv

test: lint typecheck unittest

typecheck:
	@bin/run typecheck

unittest:
	@bin/run unittest
