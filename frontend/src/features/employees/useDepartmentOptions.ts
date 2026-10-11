import { useQuery } from "@tanstack/react-query";

import { api } from "@/services/api";
import type { Department, Page } from "@/types/api";

/** Active departments for dropdowns (up to the server's page-size cap of 100). */
export function useDepartmentOptions() {
  return useQuery({
    queryKey: ["departments", "options"],
    queryFn: () => api.get<Page<Department>>("/departments/", { page_size: 100, status: "ACTIVE" }),
  });
}
