// Server-side proxy to the GoodPart GPU service. The bearer token lives only here (never in the
// browser bundle), and the browser only ever talks to our own HTTPS origin.
import { NextRequest } from "next/server";

const BASE = process.env.GOODPART_API_URL;
const TOKEN = process.env.GOODPART_API_TOKEN;

async function forward(req: NextRequest, path: string[]) {
  if (!BASE) {
    return Response.json({ detail: "Live mode is not configured: set GOODPART_API_URL on the server." }, { status: 503 });
  }
  const url = `${BASE.replace(/\/$/, "")}/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  const ct = req.headers.get("content-type");
  if (ct) headers.set("content-type", ct);
  if (TOKEN) headers.set("authorization", `Bearer ${TOKEN}`);
  try {
    const r = await fetch(url, {
      method: req.method,
      headers,
      body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.arrayBuffer(),
      cache: "no-store",
    });
    const out = new Headers();
    const rct = r.headers.get("content-type");
    if (rct) out.set("content-type", rct);
    return new Response(r.body, { status: r.status, headers: out });
  } catch {
    return Response.json({ detail: "The GPU service did not respond. Check that it is running." }, { status: 502 });
  }
}

type Ctx = { params: Promise<{ path: string[] }> };
export async function GET(req: NextRequest, { params }: Ctx) {
  return forward(req, (await params).path);
}
export async function POST(req: NextRequest, { params }: Ctx) {
  return forward(req, (await params).path);
}
export async function PUT(req: NextRequest, { params }: Ctx) {
  return forward(req, (await params).path);
}
