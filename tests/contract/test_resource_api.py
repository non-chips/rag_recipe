def _headers(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


def test_lifespan_health_and_basic_resource_round_trip(api_client) -> None:
    client, container, user_id = api_client
    assert container.started is True

    health = client.get("/actuator/health")
    assert health.status_code == 200
    assert health.json()["components"]["database"]["status"] == "UP"

    profile = client.patch(
        "/api/profile",
        headers=_headers(user_id),
        json={
            "preferred_cuisines": ["川菜"],
            "allergens": ["花生"],
            "available_appliances": ["炒锅"],
        },
    )
    assert profile.status_code == 200
    assert profile.json()["allergens"] == ["花生"]
    assert client.get("/api/profile", headers=_headers(user_id)).status_code == 200

    meal = client.post(
        "/api/meals/confirm",
        headers=_headers(user_id),
        json={
            "recipe_id": "tomato-egg",
            "event_type": "CONSUME",
            "servings": 1,
        },
    )
    assert meal.status_code == 201
    assert meal.json()["event_type"] == "CONSUME"
    assert len(client.get("/api/meals", headers=_headers(user_id)).json()) == 1

    report = client.post(
        "/api/reports/nutrition",
        headers=_headers(user_id),
        json={"days": 7, "title": "周报"},
    )
    assert report.status_code == 200
    report_id = report.json()["report"]["report_id"]
    fetched = client.get(
        f"/api/reports/nutrition/{report_id}",
        headers=_headers(user_id),
    )
    assert fetched.status_code == 200
    assert fetched.json()["report"]["metrics"] == {}

    assert client.get("/api/sessions", headers=_headers(user_id)).json() == []
    assert (
        client.get("/api/agent/runs/missing", headers=_headers(user_id)).status_code
        == 404
    )


def test_meal_confirmation_rejects_query_events(api_client) -> None:
    client, _container, user_id = api_client

    response = client.post(
        "/api/meals/confirm",
        headers=_headers(user_id),
        json={"recipe_id": "query-only", "event_type": "QUERY"},
    )

    assert response.status_code == 422

