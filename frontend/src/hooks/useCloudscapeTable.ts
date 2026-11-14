import { useCollection } from "@cloudscape-design/collection-hooks";
import type { TableProps } from "@cloudscape-design/components";

interface UseCloudscapeTableOptions<T> {
  items: T[];
  filteringFunction?: (item: T, filteringText: string) => boolean;
  sorting?: {
    defaultState?: TableProps.SortingState<T>;
  };
  pagination?: {
    pageSize?: number;
  };
}

export function useCloudscapeTable<T>({
  items,
  filteringFunction,
  sorting,
  pagination,
}: UseCloudscapeTableOptions<T>) {
  const { items: filteredItems, filterProps, paginationProps, collectionProps } = useCollection(
    items,
    {
      filtering: filteringFunction
        ? { filteringFunction }
        : undefined,
      sorting: sorting
        ? { defaultState: sorting.defaultState }
        : undefined,
      pagination: pagination
        ? { pageSize: pagination.pageSize ?? 20 }
        : undefined,
    },
  );

  return {
    items: filteredItems,
    filterProps,
    paginationProps,
    collectionProps,
  };
}
