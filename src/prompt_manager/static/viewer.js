import PhotoSwipe from "./photoswipe.esm.min.js";

const icon = (name) => `<i class="material-icons">${name}</i>`;

// items: [{id, filename, src, msrc, width, height}]; actions are handled in Python via emitEvent.
window.openViewer = (items, index, selectedId) => {
  const pswp = new PhotoSwipe({ dataSource: items, index, loop: false, bgOpacity: 1, trapFocus: false });

  pswp.on("uiRegister", () => {
    pswp.ui.registerElement({
      name: "download", order: 8, isButton: true, tagName: "a", title: "下载原图 PNG", html: icon("download"),
      onInit: (el) => {
        el.setAttribute("download", "");
        pswp.on("change", () => { el.href = `/images/${pswp.currSlide.data.filename}`; });
      },
    });
    pswp.ui.registerElement({
      name: "delete", order: 9, isButton: true, title: "删除", html: icon("delete_outline"),
      onClick: () => emitEvent("viewer_delete", pswp.currSlide.data.id),
    });
    pswp.ui.registerElement({
      name: "select", order: 10, appendTo: "root", tagName: "button",
      onInit: (el) => {
        const update = () => {
          const selected = pswp.currSlide.data.id === selectedId;
          el.classList.toggle("selected", selected);
          el.innerHTML = icon(selected ? "check_circle" : "radio_button_unchecked") + (selected ? "已选用" : "选用");
        };
        el.onclick = () => {
          selectedId = selectedId === pswp.currSlide.data.id ? null : pswp.currSlide.data.id;
          emitEvent("viewer_select", selectedId);
          update();
        };
        pswp.on("change", update);
      },
    });
  });
  pswp.on("close", () => emitEvent("viewer_closed"));
  pswp.init();
  window.viewer = pswp;
};

window.viewerRemove = (id) => {
  const pswp = window.viewer;
  const items = pswp.options.dataSource;
  const index = items.findIndex((item) => item.id === id);
  items.splice(index, 1);
  if (!items.length) return pswp.close();
  if (index >= items.length) pswp.goTo(items.length - 1);
  for (let i = index - 1; i <= index + 1; i++) {
    if (i >= 0 && i < items.length) pswp.refreshSlideContent(i);
  }
  pswp.dispatch("change");
};
