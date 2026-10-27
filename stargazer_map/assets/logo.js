// GitHub avatars often pad a wide logo into a square with a plain background. Crop
// those margins so the logo fills its frame; photos and full-bleed avatars stay as
// they are. Needs the avatar served with CORS (crossorigin="anonymous").
(function(){
  var img = document.querySelector('img.logo.avatar');
  if (!img) return;

  function trim(){
    var w = img.naturalWidth, h = img.naturalHeight;
    if (!w || !h) return;
    var c = document.createElement('canvas');
    c.width = w; c.height = h;
    var ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0);
    var px;
    try { px = ctx.getImageData(0, 0, w, h).data; } catch (e) { return; }  // no CORS
    // Background: the top-left pixel. JPEG noise needs some tolerance.
    var r = px[0], g = px[1], b = px[2];
    var top = h, bottom = -1, left = w, right = -1;
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        var i = (y * w + x) * 4;
        if (Math.abs(px[i] - r) + Math.abs(px[i+1] - g) + Math.abs(px[i+2] - b) < 48) continue;
        if (y < top) top = y;
        if (y > bottom) bottom = y;
        if (x < left) left = x;
        if (x > right) right = x;
      }
    }
    if (bottom < 0) return;  // a blank image
    var pad = Math.round(Math.max(w, h) * .03);
    top = Math.max(0, top - pad); bottom = Math.min(h - 1, bottom + pad);
    left = Math.max(0, left - pad); right = Math.min(w - 1, right + pad);
    var cw = right - left + 1, ch = bottom - top + 1;
    if (cw * ch > .9 * w * h) return;  // no margin worth cropping
    var out = document.createElement('canvas');
    out.width = cw; out.height = ch;
    out.getContext('2d').drawImage(c, left, top, cw, ch, 0, 0, cw, ch);
    img.src = out.toDataURL();
    img.classList.add('trimmed');
  }

  if (img.complete) trim(); else img.addEventListener('load', trim, {once: true});
})();
