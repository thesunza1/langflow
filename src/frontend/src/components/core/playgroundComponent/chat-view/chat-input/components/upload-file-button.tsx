import { useTranslation } from "react-i18next";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { Button } from "@/components/ui/button";
import { CHAT_UPLOAD_ATTACHMENT_ACCEPT } from "@/constants/file-upload-constants";

interface UploadFileButtonProps {
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  handleFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
  handleButtonClick: () => void;
}

const UploadFileButton = ({
  fileInputRef,
  handleFileChange,
  handleButtonClick,
}: UploadFileButtonProps) => {
  const { t } = useTranslation();

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    handleButtonClick();
  };

  return (
    <ShadTooltip
      styleClasses="z-50"
      side="right"
      content={t("chat.attachFileTooltip")}
    >
      <div>
        <input
          disabled={false}
          type="file"
          ref={fileInputRef}
          style={{ display: "none" }}
          onChange={handleFileChange}
          accept={CHAT_UPLOAD_ATTACHMENT_ACCEPT}
        />
        <Button
          disabled={false}
          className="h-7 w-7 px-0 flex items-center justify-center text-muted-foreground hover:text-primary"
          onClick={handleClick}
          unstyled
        >
          <ForwardedIconComponent className="h-[18px] w-[18px]" name="File" />
        </Button>
      </div>
    </ShadTooltip>
  );
};

export default UploadFileButton;
