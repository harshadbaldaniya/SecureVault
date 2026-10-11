/** Minimal WebSocket stand-in: tests drive it explicitly instead of touching the network. */
export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  readonly url: string;
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  /** Simulate the server accepting the connection. */
  open() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  /** Simulate a server message. */
  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  /** Simulate the server closing the socket with a code. */
  serverClose(code: number) {
    this.readyState = 3;
    this.onclose?.({ code });
  }

  send() {}

  close() {
    this.readyState = 3;
  }

  static latest(): FakeWebSocket | undefined {
    return FakeWebSocket.instances.at(-1);
  }
}
