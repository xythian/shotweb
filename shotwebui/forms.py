#
# Time to start really smoking the crazy talk
#

import string
from shotwebui.controls import Control, LiteralControl
from shotwebui.resources import JavaScriptTracker


class AjaxForm(Control):
    method = "POST"
    action = "/"
    noscriptaction = "/"
    async = True

    asyncT = string.Template('<div id="$clientid"><form id="${clientid}_form">')
    noasyncT = string.Template('<div id="$clientid"><form id="${clientid}_form">')

    def init(self):
        JavaScriptTracker.get(self.request).depends('mochikit')
        super(AjaxForm, self).init()
        self.formid = self.clientid
        
    def render(self, out):
        if self.async:
            t = self.asyncT
        else:
            t = self.noasyncT
        out.append(t.substitute({'clientid' : self.formid}))
        super(AjaxForm, self).render(out)
        out.append("</form></div>")
