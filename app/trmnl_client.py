import httpx


class TRMNLClient:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def push_data(self, data: dict, strategy: str | None = None) -> dict:
        """Push data to TRMNL webhook.

        Valid strategies: 'deep_merge' (merge nested keys) or 'stream' (append arrays).
        Omit strategy (default) to fully replace all merge_variables.
        """
        payload: dict = {"merge_variables": data}
        if strategy is not None:
            payload["merge_strategy"] = strategy

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if not response.is_success:
                raise httpx.HTTPStatusError(
                    f"{response.status_code} from TRMNL: {response.text}",
                    request=response.request,
                    response=response,
                )

        return response.json()
