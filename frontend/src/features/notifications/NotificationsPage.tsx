import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Alert, Badge, Button, EmptyState, PageHeader, PageLoader, Pagination, TextLink } from "@/components/ui";
import { api, ApiError } from "@/services/api";
import type { AppNotification, Page } from "@/types/api";

const PAGE_SIZE = 25;
// Same scale as alert severity: high and critical are both red, so one level never reads as two different colours.
const PRIORITY_TONE = { LOW: "slate", NORMAL: "blue", HIGH: "red", CRITICAL: "red" } as const;

export const UNREAD_KEY = ["notifications", "unread"] as const;

/** Unread badge for the navigation. Polls as a fallback; real-time pushes also invalidate this query. */
export function NotificationBell() {
  const unread = useQuery({
    queryKey: UNREAD_KEY,
    queryFn: () => api.get<{ unread: number }>("/notifications/unread-count/"),
    refetchInterval: 30_000,
  });
  const count = unread.data?.unread ?? 0;
  return (
    <Link to="/notifications" className="flex items-center justify-between rounded-md px-3 py-2 text-sm hover:bg-white/5">
      <span>
        Notifications
        {count > 0 && <span className="sr-only">, {count} unread</span>}
      </span>
      {count > 0 && (
        <span aria-hidden="true" className="rounded-full bg-red-600 px-2 py-0.5 text-xs font-semibold text-white">
          {count > 99 ? "99+" : count}
        </span>
      )}
    </Link>
  );
}

export function NotificationsPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const params = { page, is_read: unreadOnly ? false : undefined };
  const query = useQuery({
    queryKey: ["notifications", "list", params],
    queryFn: () => api.get<Page<AppNotification>>("/notifications/", params),
    placeholderData: (previous) => previous,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["notifications"] });
  const markRead = useMutation({ mutationFn: (id: string) => api.post(`/notifications/${id}/read/`), onSuccess: refresh });
  const markAll = useMutation({ mutationFn: () => api.post("/notifications/read-all/"), onSuccess: refresh });

  return (
    <>
      <PageHeader
        title="Notifications"
        description="Security and workflow alerts. They never contain secrets."
        actions={
          <div className="flex gap-2">
            <Button variant="secondary" aria-pressed={unreadOnly} onClick={() => { setUnreadOnly((v) => !v); setPage(1); }}>
              Unread only
            </Button>
            <Button onClick={() => markAll.mutate()} loading={markAll.isPending}>
              Mark all as read
            </Button>
          </div>
        }
      />
      {(markRead.isError || markAll.isError) && (
        <Alert tone="error" className="mb-4">
          {(() => {
            const error = markRead.error ?? markAll.error;
            return error instanceof ApiError ? error.message : "Could not update your notifications. Nothing was changed.";
          })()}
        </Alert>
      )}
      {query.isPending ? (
        <PageLoader />
      ) : query.isError ? (
        <Alert tone="error">{query.error instanceof ApiError ? query.error.message : "Could not load notifications."}</Alert>
      ) : query.data.results.length === 0 ? (
        <EmptyState title="No notifications" />
      ) : (
        <>
          <ul className="space-y-2" aria-label="Notifications">
            {query.data.results.map((n) => (
              <li key={n.id} className={`rounded-lg p-4 ring-1 ${n.is_read ? "bg-white ring-slate-200" : "bg-blue-50 ring-blue-200"}`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-medium">
                      {!n.is_read && <span className="sr-only">Unread: </span>}
                      {n.title}
                    </p>
                    {n.message && <p className="mt-1 text-sm text-slate-600">{n.message}</p>}
                    <p className="mt-1 text-xs text-slate-600">
                      <time dateTime={n.created_at}>{new Date(n.created_at).toLocaleString()}</time>
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {n.priority !== "NORMAL" && <Badge tone={PRIORITY_TONE[n.priority]}>{n.priority.toLowerCase()}</Badge>}
                    {n.link && (
                      <TextLink to={n.link} className="text-sm" onClick={() => !n.is_read && markRead.mutate(n.id)}>
                        Open
                      </TextLink>
                    )}
                    <span className="inline-flex sm:w-24 sm:justify-end">
                      {!n.is_read && (
                        <Button variant="ghost" size="sm" onClick={() => markRead.mutate(n.id)} aria-label={`Mark read: ${n.title}`}>
                          Mark read
                        </Button>
                      )}
                    </span>
                  </div>
                </div>
              </li>
            ))}
          </ul>
          <Pagination page={page} pageSize={PAGE_SIZE} count={query.data.count} onPage={setPage} />
        </>
      )}
    </>
  );
}
