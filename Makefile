SHELL := /bin/sh

AWS_REGION ?= us-east-1
AWS_PROFILE ?= navteca
IMAGE_URI ?= 607399646027.dkr.ecr.us-east-1.amazonaws.com/navteca/images/weather-intelligence:latest
IMAGE_PLATFORMS ?= linux/amd64,linux/arm64
LOCAL_IMAGE_PLATFORM ?= linux/amd64
BUILDX_BUILDER ?=

.PHONY: image ecr-login build-image push-image run-image scan-secrets

image: ecr-login push-image

ecr-login:
	@registry="$${IMAGE_URI%%/*}"; \
	printf 'Logging into ECR registry %s with AWS profile %s in region %s\n' "$$registry" "$(AWS_PROFILE)" "$(AWS_REGION)"; \
	aws ecr get-login-password --region "$(AWS_REGION)" --profile "$(AWS_PROFILE)" | \
		docker login --username AWS --password-stdin "$$registry"

build-image:
	@case "$(IMAGE_URI)" in \
		*:* ) ;; \
		* ) printf 'IMAGE_URI must include a tag, for example registry/repo:0.1.2\n' >&2; exit 1 ;; \
	esac; \
	builder_arg=""; \
	if [ -n "$(BUILDX_BUILDER)" ]; then builder_arg="--builder $(BUILDX_BUILDER)"; fi; \
	printf 'Building local image %s with:\n' "$(IMAGE_URI)"; \
	printf 'AWS_PROFILE=%s\n' "$(AWS_PROFILE)"; \
	printf 'AWS_REGION=%s\n' "$(AWS_REGION)"; \
	printf 'LOCAL_IMAGE_PLATFORM=%s\n' "$(LOCAL_IMAGE_PLATFORM)"; \
	docker buildx build $$builder_arg \
		--platform "$(LOCAL_IMAGE_PLATFORM)" \
		-t "$(IMAGE_URI)" \
		--load \
		.

push-image:
	@case "$(IMAGE_URI)" in \
		*:* ) ;; \
		* ) printf 'IMAGE_URI must include a tag, for example registry/repo:0.1.2\n' >&2; exit 1 ;; \
	esac; \
	builder_arg=""; \
	if [ -n "$(BUILDX_BUILDER)" ]; then builder_arg="--builder $(BUILDX_BUILDER)"; fi; \
	printf 'Building and pushing multi-arch image %s with:\n' "$(IMAGE_URI)"; \
	printf 'AWS_PROFILE=%s\n' "$(AWS_PROFILE)"; \
	printf 'AWS_REGION=%s\n' "$(AWS_REGION)"; \
	printf 'IMAGE_PLATFORMS=%s\n' "$(IMAGE_PLATFORMS)"; \
	docker buildx build $$builder_arg \
		--platform "$(IMAGE_PLATFORMS)" \
		-t "$(IMAGE_URI)" \
		--push \
		.

run-image:
	docker run --rm -it --platform "$(LOCAL_IMAGE_PLATFORM)" "$(IMAGE_URI)"

scan-secrets:
	@command -v gitleaks >/dev/null 2>&1 || { \
		printf 'gitleaks is not installed. Install it first: https://github.com/gitleaks/gitleaks\n' >&2; \
		exit 1; \
	}
	gitleaks detect --source . --no-git --verbose
