use tokio::net::{TcpListener, TcpStream};
use tokio::io::{AsyncWriteExt, BufReader, AsyncBufReadExt};
use tokio::sync::{mpsc, oneshot};
use dashmap::DashMap;
use serde_json::Value;
use std::sync::{Arc, atomic::{AtomicU64, Ordering}};

const PYTHON_IPC_PORT: u16 = 8299;
const PUBLIC_PORT: u16 = 8300;

type ClientId = u64;
type ReqId = u64;

static NEXT_CLIENT_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Debug)]
struct QueryPayload {
    client_id: ClientId,
    req_id: ReqId,
    query: String,
    responder: oneshot::Sender<String>,
}

type PendingMap = Arc<DashMap<String, oneshot::Sender<String>>>;

async fn execution_coordinator(mut rx_ring: mpsc::Receiver<QueryPayload>, engine_socket: TcpStream, pending_requests: PendingMap) {
    let (engine_read, mut engine_write) = engine_socket.into_split();

    let pending_clone = pending_requests.clone();
    tokio::spawn(async move {
        let mut reader = BufReader::new(engine_read);
        let mut line = String::new();
        loop {
            line.clear();
            if reader.read_line(&mut line).await.unwrap_or(0) == 0 {
                std::process::exit(1);
            }
            if let Ok(json) = serde_json::from_str::<Value>(&line) {
                if let Some(req_id_val) = json.get("_req_id") {
                    if let Some(req_id_str) = req_id_val.as_str() {
                        if let Some((_, responder)) = pending_clone.remove(req_id_str) {
                            if let Some(payload) = json.get("payload") {
                                let _ = responder.send(payload.to_string());
                            } else {
                                let _ = responder.send(line.clone());
                            }
                        }
                    }
                }
            }
        }
    });

    while let Some(payload) = rx_ring.recv().await {
        let tracking_id = format!("{}_{}", payload.client_id, payload.req_id);
        pending_requests.insert(tracking_id.clone(), payload.responder);
        
        let out_str = if payload.query.starts_with('{') {
            let mut v: Value = serde_json::from_str(&payload.query).unwrap_or(serde_json::json!({}));
            v["_req_id"] = serde_json::json!(tracking_id);
            v.to_string()
        } else {
            let v = serde_json::json!({
                "action": "query",
                "query": payload.query,
                "_req_id": tracking_id
            });
            v.to_string()
        };
        
        if let Err(_) = engine_write.write_all(format!("{}\n", out_str).as_bytes()).await {
            break;
        }
    }
}

async fn handle_client(mut socket: TcpStream, tx_ring: mpsc::Sender<QueryPayload>) -> std::io::Result<()> {
    let (mut read_half, mut write_half) = socket.split();
    let mut reader = BufReader::new(&mut read_half);
    let mut line = String::new();
    let cid = NEXT_CLIENT_ID.fetch_add(1, Ordering::SeqCst);
    let mut req_counter: ReqId = 0;

    loop {
        line.clear();
        let bytes_read = reader.read_line(&mut line).await?;
        if bytes_read == 0 {
            break;
        }

        req_counter += 1;
        let query = line.trim().to_string();
        if query.is_empty() {
            continue;
        }

        let (tx_resp, rx_resp) = oneshot::channel();
        let payload = QueryPayload {
            client_id: cid,
            req_id: req_counter,
            query,
            responder: tx_resp,
        };

        if tx_ring.send(payload).await.is_err() {
            break;
        }

        if let Ok(mut response) = rx_resp.await {
            response.push('\n');
            write_half.write_all(response.as_bytes()).await?;
        }
    }
    Ok(())
}

#[tokio::main]
async fn main() -> std::io::Result<()> {
    let (tx_ring, rx_ring) = mpsc::channel::<QueryPayload>(100_000);
    
    let engine_socket = match TcpStream::connect(("127.0.0.1", PYTHON_IPC_PORT)).await {
        Ok(s) => s,
        Err(_) => return Ok(()),
    };

    let pending: PendingMap = Arc::new(DashMap::new());
    tokio::spawn(async move {
        execution_coordinator(rx_ring, engine_socket, pending).await;
    });

    let listener = TcpListener::bind(("0.0.0.0", PUBLIC_PORT)).await?;
    
    while let Ok((socket, _)) = listener.accept().await {
        let tx = tx_ring.clone();
        tokio::spawn(async move {
            let _ = handle_client(socket, tx).await;
        });
    }
    Ok(())
}
