"""mitmproxy addon: dump WebSocket messages"""
from mitmproxy import ctx, websocket

def websocket_message(flow):
    msg = flow.websocket.messages[-1]
    direction = "->" if msg.from_client else "<-"
    content = msg.content
    ctx.log.info(f"WS {direction} {content[:500]}")
    # also print raw to stderr for easy viewing
    print(f"\n{'='*60}\nWS {direction} ({len(content)} bytes)\n{content[:2000]}\n{'='*60}", flush=True)
