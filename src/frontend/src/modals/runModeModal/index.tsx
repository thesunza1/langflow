import { useState } from "react";
import { useTranslation } from "react-i18next";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { cn } from "@/utils/utils";

type RunModeModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  nodeName: string;
  nearestBuiltNodeName?: string;
  onRunFromNearest: () => void;
  onRunFromStart: () => void;
  onRunWithExistingStop: () => void;
  onRunWithExistingAll: () => void;
};

export default function RunModeModal({
  open,
  onOpenChange,
  nodeName,
  nearestBuiltNodeName,
  onRunFromNearest,
  onRunFromStart,
  onRunWithExistingStop,
  onRunWithExistingAll,
}: RunModeModalProps) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<
    "nearest" | "start" | "existing-stop" | "existing-all"
  >("nearest");

  const handleRun = () => {
    if (mode === "nearest") {
      onRunFromNearest();
    } else if (mode === "start") {
      onRunFromStart();
    } else if (mode === "existing-stop") {
      onRunWithExistingStop();
    } else if (mode === "existing-all") {
      onRunWithExistingAll();
    }
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <ForwardedIconComponent
              name="Zap"
              className="h-5 w-5 text-accent-foreground"
            />
            {t("runMode.title", "Run Options")}
          </DialogTitle>
          <DialogDescription>
            {t("runMode.description", {
              nodeName,
              defaultValue: `Component "${nodeName}" has upstream nodes that were already built. How would you like to run?`,
            })}
          </DialogDescription>
        </DialogHeader>

        <RadioGroup
          value={mode}
          onValueChange={(v) =>
            setMode(v as "nearest" | "start" | "existing-stop" | "existing-all")
          }
          className="gap-2"
          data-testid="run-mode-radio-group"
        >
          <Label
            htmlFor="mode-nearest"
            className={cn(
              "flex cursor-pointer items-start gap-3 rounded-lg border p-4 hover:bg-accent/50",
              mode === "nearest" && "border-primary bg-accent/30",
            )}
          >
            <RadioGroupItem
              value="nearest"
              id="mode-nearest"
              className="mt-0.5"
            />
            <div className="flex flex-col gap-1">
              <span className="text-sm font-medium">
                {t("runMode.runFromNearest", "Run and stop here")}
              </span>
              <span className="text-xs text-muted-foreground">
                {nearestBuiltNodeName
                  ? t("runMode.runFromNearestDesc", {
                      nodeName: nearestBuiltNodeName,
                      defaultValue: `Run upstream using cached results, stop at this node`,
                    })
                  : t(
                      "runMode.runFromNearestDescGeneric",
                      "Run upstream using cached results, stop at this node",
                    )}
              </span>
            </div>
          </Label>

          <Label
            htmlFor="mode-start"
            className={cn(
              "flex cursor-pointer items-start gap-3 rounded-lg border p-4 hover:bg-accent/50",
              mode === "start" && "border-primary bg-accent/30",
            )}
          >
            <RadioGroupItem value="start" id="mode-start" className="mt-0.5" />
            <div className="flex flex-col gap-1">
              <span className="text-sm font-medium">
                {t("runMode.runFromStart", "Run from beginning (re-run all)")}
              </span>
              <span className="text-xs text-muted-foreground">
                {t(
                  "runMode.runFromStartDesc",
                  "Re-run every component from the start of the flow to the end",
                )}
              </span>
            </div>
          </Label>

          <Label
            htmlFor="mode-existing-stop"
            className={cn(
              "flex cursor-pointer items-start gap-3 rounded-lg border p-4 hover:bg-accent/50",
              mode === "existing-stop" && "border-primary bg-accent/30",
            )}
          >
            <RadioGroupItem
              value="existing-stop"
              id="mode-existing-stop"
              className="mt-0.5"
            />
            <div className="flex flex-col gap-1">
              <span className="text-sm font-medium">
                {t(
                  "runMode.runWithExistingStop",
                  "Run and stop here (use existing)",
                )}
              </span>
              <span className="text-xs text-muted-foreground">
                {t(
                  "runMode.runWithExistingStopDesc",
                  "Use cached results for upstream, build this node, then stop",
                )}
              </span>
            </div>
          </Label>

          <Label
            htmlFor="mode-existing-all"
            className={cn(
              "flex cursor-pointer items-start gap-3 rounded-lg border p-4 hover:bg-accent/50",
              mode === "existing-all" && "border-primary bg-accent/30",
            )}
          >
            <RadioGroupItem
              value="existing-all"
              id="mode-existing-all"
              className="mt-0.5"
            />
            <div className="flex flex-col gap-1">
              <span className="text-sm font-medium">
                {t(
                  "runMode.runWithExistingAll",
                  "Run from here to end (use existing)",
                )}
              </span>
              <span className="text-xs text-muted-foreground">
                {t(
                  "runMode.runWithExistingAllDesc",
                  "Use cached results for upstream, run from this node to the end",
                )}
              </span>
            </div>
          </Label>
        </RadioGroup>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            data-testid="run-mode-cancel-button"
          >
            {t("cancel", "Cancel")}
          </Button>
          <Button onClick={handleRun} data-testid="run-mode-run-button">
            {t("run", "Run")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
