"""OpenSky OAuth2 client credentials。token 提前 60 秒刷新。"""

from __future__ import annotations

import time

import httpx

TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
)
REFRESH_MARGIN_S = 60


class TokenProvider:
    def __init__(self, client_id: str, client_secret: str, clock=time.monotonic) -> None:
        self._id = client_id
        self._secret = client_secret
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0

    def needs_refresh(self) -> bool:
        return self._token is None or self._clock() >= self._expires_at - REFRESH_MARGIN_S

    def invalidate(self) -> None:
        self._token = None

    async def get(self, client: httpx.AsyncClient) -> str:
        if self.needs_refresh():
            resp = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._id,
                    "client_secret": self._secret,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            self._token = body["access_token"]
            self._expires_at = self._clock() + float(body.get("expires_in", 1800))
        assert self._token is not None
        return self._token
