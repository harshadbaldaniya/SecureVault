import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { AuthProvider } from "@/features/authentication/AuthContext";
import { ApiError } from "@/services/api";

export function makeQueryClient({ retry = true }: { retry?: boolean } = {}): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // Never retry auth/permission/validation failures; retry transient network/server errors once.
        retry: (count, error) => retry && !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 1,
      },
    },
  });
}

export function Providers({ client, children }: { client: QueryClient; children: ReactNode }) {
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}
