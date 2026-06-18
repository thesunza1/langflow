import type React from "react";
import { Button } from "@/components/ui/button";

interface NoInputViewProps {
  sendMessage: (args: { repeat: number }) => Promise<void>;
}

const NoInputView: React.FC<NoInputViewProps> = ({ sendMessage }) => {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center">
      <div className="flex w-full flex-col items-center justify-center gap-3 rounded-md border border-input bg-muted p-2 py-4">
        <Button
          data-testid="button-send"
          className="font-semibold"
          onClick={async () => {
            await sendMessage({
              repeat: 1,
            });
          }}
        >
          Run Flow
        </Button>

        <p className="text-muted-foreground">
          Add a{" "}
          <a
            className="underline underline-offset-4"
            target="_blank"
            href="https://docs.langflow.org/components-io#chat-input"
            rel="noopener"
          >
            Chat Input
          </a>{" "}
          component to your flow to send messages.
        </p>
      </div>
    </div>
  );
};

export default NoInputView;
