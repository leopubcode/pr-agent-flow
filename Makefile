.PHONY: infra-apply infra-destroy consumer-install consumer-run test

infra-apply:
	cd infra && terraform init && terraform apply

infra-destroy:
	cd infra && terraform destroy

consumer-install:
	pip install -e "consumer/[dev]"

consumer-run:
	python -m consumer.main

test:
	cd webhook && python -m pytest tests/
	cd consumer && python -m pytest tests/
