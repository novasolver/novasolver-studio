# SPDX-License-Identifier: GPL-3.0-or-later
# NovaSolver Studio workbench: send the part to Studio, bring the Genesis shape back. The buttons can also be put on
# other toolbars with Tools > Customize > Toolbars once the workbench has been opened.
#
# FreeCAD runs this file with exec() inside a function: names defined here are not visible from inside the class,
# so every method imports what it needs itself (and there is no __file__; the Mod folder is on sys.path).
import FreeCADGui


class NovaSolverStudioWorkbench(FreeCADGui.Workbench):
    MenuText = "NovaSolver Studio"
    ToolTip = "Analyse the part and run Genesis in NovaSolver Studio (free, local)"

    def __init__(self):
        import os
        import nss_link
        self.__class__.Icon = os.path.join(os.path.dirname(nss_link.__file__), "Resources", "icons",
                                           "NovaSolverStudio.svg")

    def Initialize(self):
        import nss_commands
        cmds = nss_commands.register()
        self.appendToolbar("NovaSolver Studio", cmds)
        self.appendMenu("NovaSolver Studio", cmds)

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(NovaSolverStudioWorkbench())
