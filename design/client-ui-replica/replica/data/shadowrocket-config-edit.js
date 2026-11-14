window.REPLICA={
 "app": "shadowrocket",
 "screen": "config-edit",
 "theme": "shadowrocket",
 "reference": "../screens/shadowrocket/config-edit_1.png",
 "nav": {
  "left": "back",
  "title": "latest-shadowrocket.conf",
  "right": "plus"
 },
 "status": {
  "time": "01:35",
  "battery": "80"
 },
 "content_top": 132,
 "row_h": 48.8,
 "group_gap": 37.3,
 "groups": [
  {
   "rows": [
    {
     "label": "通用",
     "subhub": "只写一部分",
     "maps_to": "[General]",
     "accessory": "chevron",
     "detail": "5"
    },
    {
     "label": "规则",
     "subhub": "写入",
     "maps_to": "[Rule]",
     "accessory": "chevron",
     "detail": "35639"
    },
    {
     "label": "Hosts",
     "subhub": "写入",
     "maps_to": "[Host]（intent shadowrocket_host_records）",
     "accessory": "chevron",
     "detail": "1"
    },
    {
     "label": "URL 重写",
     "subhub": "写入",
     "maps_to": "[URL Rewrite]（intent shadowrocket_url_rewrite）",
     "accessory": "chevron",
     "detail": "2"
    },
    {
     "label": "头部重写",
     "subhub": "不写",
     "maps_to": "[Header Rewrite]",
     "accessory": "chevron",
     "detail": "0"
    },
    {
     "label": "正文重写",
     "subhub": "不写",
     "maps_to": null,
     "accessory": "chevron",
     "detail": "0"
    },
    {
     "label": "本地映射",
     "subhub": "不写",
     "maps_to": "[Map Local]",
     "accessory": "chevron",
     "detail": "0"
    },
    {
     "label": "HTTPS 解密",
     "subhub": "只写一部分",
     "maps_to": "[MITM]",
     "accessory": "chevron",
     "detail": "0"
    },
    {
     "label": "脚本",
     "subhub": "只写一部分",
     "maps_to": "[Script]（http-request / http-response）",
     "accessory": "chevron",
     "detail": "0"
    },
    {
     "label": "代理分组",
     "subhub": "写入",
     "maps_to": "[Proxy Group]",
     "accessory": "chevron",
     "detail": "1"
    }
   ]
  },
  {
   "rows": [
    {
     "label": "规则集 URL",
     "subhub": "还没核对",
     "maps_to": null,
     "accessory": "chevron",
     "detail": "0/0"
    },
    {
     "label": "脚本 URL",
     "subhub": "还没核对",
     "maps_to": null,
     "accessory": "chevron",
     "detail": "0/0"
    }
   ]
  },
  {
   "rows": [
    {
     "label": "编辑纯文本",
     "subhub": "不适用（动作/导航）",
     "maps_to": null
    },
    {
     "label": "编译配置",
     "subhub": "不适用（动作/导航）",
     "maps_to": null
    },
    {
     "label": "扩展",
     "subhub": "不适用（动作/导航）",
     "maps_to": null
    },
    {
     "label": "导出配置",
     "subhub": "不适用（动作/导航）",
     "maps_to": null
    }
   ]
  },
  {
   "rows": [
    {
     "label": "复制",
     "subhub": "不适用（动作/导航）",
     "maps_to": null
    },
    {
     "label": "替换策略",
     "subhub": "不适用（动作/导航）",
     "maps_to": null
    },
    {
     "label": "测试规则",
     "subhub": "不适用（动作/导航）",
     "maps_to": null
    }
   ]
  }
 ],
 "tabbar": {
  "x": [
   21,
   381
  ],
  "selected": 1,
  "items": [
   {
    "icon": "home",
    "label": "首页"
   },
   {
    "icon": "folder",
    "label": "配置"
   },
   {
    "icon": "activity",
    "label": "数据"
   },
   {
    "icon": "gear",
    "label": "设置"
   }
  ]
 }
};
