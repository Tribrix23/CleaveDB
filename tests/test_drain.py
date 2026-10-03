import asyncio
import json
import pytest
import time

@pytest.mark.asyncio
async def test_drain_before():
    reader, writer = await asyncio.open_connection('127.0.0.1', 8299)
    
    # Register test user
    auth_payload = {"action": "register", "username": "pytest_drain", "password": "password", "dev_password": "dev", "question": "q", "answer": "a"}
    writer.write((json.dumps(auth_payload) + "\n").encode())
    await writer.drain()
    await reader.readline() # ignore result, might already exist
    
    # Login
    login_payload = {"action": "login", "username": "pytest_drain", "password": "password"}
    writer.write((json.dumps(login_payload) + "\n").encode())
    await writer.drain()
    await reader.readline()

    queries = [
        'POUR INTO drainbucket "doc1" {"name": "Doc1", "_created_at": 1000}',
        'POUR INTO drainbucket "doc2" {"name": "Doc2", "created_at": 1700000000}',
        'POUR INTO drainbucket "doc3" {"name": "Doc3", "created_at": 1900000000}'
    ]
    for q in queries:
        writer.write((q + "\n").encode())
        await writer.drain()
        await reader.readline()

    # Query initial
    writer.write(('FIND drainbucket\n').encode())
    await writer.drain()
    res = await reader.readline()
    data = json.loads(res.decode().strip())
    assert len(data[0]["documents"]) >= 3

    # Drain BEFORE 2000
    writer.write(('DRAIN drainbucket BEFORE "2000"\n').encode())
    await writer.drain()
    res = await reader.readline()
    drain1 = json.loads(res.decode().strip())
    assert drain1[0]["status"] == "ok"
    
    writer.write(('FIND drainbucket\n').encode())
    await writer.drain()
    res = await reader.readline()
    data = json.loads(res.decode().strip())
    names = [d["body"]["name"] for d in data[0]["documents"]]
    assert "Doc1" not in names
    assert "Doc2" in names
    assert "Doc3" in names
    
    # Drain BEFORE 2025
    writer.write(('DRAIN drainbucket BEFORE "2025-01-01"\n').encode())
    await writer.drain()
    res = await reader.readline()
    drain2 = json.loads(res.decode().strip())
    assert drain2[0]["status"] == "ok"

    writer.write(('FIND drainbucket\n').encode())
    await writer.drain()
    res = await reader.readline()
    data = json.loads(res.decode().strip())
    names = [d["body"]["name"] for d in data[0]["documents"]]
    assert "Doc2" not in names
    assert "Doc3" in names

if __name__ == "__main__":
    asyncio.run(test_drain_before())
