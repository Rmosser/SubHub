export interface PoolDefinition {
  id: string;
  display_name: string;
  sort_order: number;
  pseudo: boolean;
  editable: boolean;
}

export interface PoolStatus {
  id: string;
  display_name: string;
  node_count: number;
  renderable_node_count: number;
  last_refresh_at: string;
  sources: Record<string, number>;
  pseudo: boolean;
}
